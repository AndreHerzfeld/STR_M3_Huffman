#define _GNU_SOURCE
#include "huffman.h"
#include "timing.h"
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <sys/prctl.h>
#include <unistd.h>

enum { PERIOD_US = 2500, MEM_WORDS = 1024 * 1024 };
static Huffman huffman;
static uint8_t input[INPUT_SIZE];
static uint32_t shared[1024];
static pthread_mutex_t medium = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t event = PTHREAD_COND_INITIALIZER;
static atomic_bool stop;
static uint64_t release_ns, hold_ns;
static unsigned requested, completed, sample_count;
static bool coverage_cases;
static volatile uint32_t stress_memory[MEM_WORDS];

static void check(int error, const char *label)
{
    if (error) {
        fprintf(stderr, "%s: %s\n", label, strerror(error));
        exit(1);
    }
}

static void sleep_until(uint64_t ns)
{
    struct timespec instant = {ns / UINT64_C(1000000000), ns % UINT64_C(1000000000)};
    int error;
    do {
        error = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &instant, NULL);
    } while (error == EINTR);
    check(error, "clock_nanosleep");
}

static void *event_source(void *unused)
{
    (void)unused;
    uint64_t next = monotonic_ns() + PERIOD_US * UINT64_C(1000);
    for (unsigned i = 1; i <= sample_count; ++i) {
        if (coverage_cases) {
            fill_case(input, i);
        } else {
            fill_input(input, i);
        }
        sleep_until(next);
        pthread_mutex_lock(&gate);
        release_ns = monotonic_ns();
        requested = i;
        pthread_cond_broadcast(&event);
        while (completed != i) {
            pthread_cond_wait(&event, &gate);
        }
        pthread_mutex_unlock(&gate);
        uint64_t now = monotonic_ns();
        /* Preserve one outstanding event even after an overrun. */
        next += PERIOD_US * UINT64_C(1000);
        if (next <= now) {
            next = now + PERIOD_US * UINT64_C(1000);
        }
    }
    return NULL;
}

struct worker_config { unsigned period_us, hold_us, start_us, rate; };

static void *periodic_worker(void *arg)
{
    const struct worker_config *cfg = arg;
    uint64_t next = monotonic_ns() + cfg->start_us * UINT64_C(1000);
    while (!atomic_load_explicit(&stop, memory_order_relaxed)) {
        sleep_until(next);
        pthread_mutex_lock(&medium);
        uint64_t finish = monotonic_ns() + cfg->hold_us * UINT64_C(1000);
        unsigned index = 0;
        do {
            shared[index++ & 1023] += cfg->rate;
        } while (monotonic_ns() < finish);
        pthread_mutex_unlock(&medium);
        next += cfg->period_us * UINT64_C(1000);
        uint64_t now = monotonic_ns();
        if (next <= now) {
            next = now + cfg->period_us * UINT64_C(1000);
        }
    }
    return NULL;
}

static void stress_loop(void)
{
    /* A separate process competes for CPU, cache and memory. */
    for (;;) {
        for (unsigned i = 0; i < MEM_WORDS; i += 16) {
            stress_memory[i] = stress_memory[i] * 1664525u + 1013904223u;
        }
    }
}

int main(int argc, char **argv)
{
    if (argc != 5) {
        fprintf(stderr, "Uso: %s ETAPA AMOSTRAS CPU MODO(aleatorio|casos)\n", argv[0]);
        return 2;
    }
    unsigned stage = strtoul(argv[1], NULL, 10);
    sample_count = strtoul(argv[2], NULL, 10);
    unsigned core = strtoul(argv[3], NULL, 10);
    coverage_cases = strcmp(argv[4], "casos") == 0;
    if (stage < 1 || stage > 4 || !sample_count || core >= CPU_SETSIZE) {
        return 2;
    }
    cpu_set_t affinity;
    CPU_ZERO(&affinity);
    CPU_SET(core, &affinity);
    check(sched_setaffinity(0, sizeof affinity, &affinity) == 0 ? 0 : errno, "afinidade");
    size_t size = sample_count;
    uint64_t *elapsed = calloc(size, sizeof *elapsed);
    if (!elapsed) {
        return 1;
    }
    unsigned invalid = 0;
    pthread_t producer, workers[2];
    struct worker_config cfg[] = {{3700, 330, 200, 1}, {7100, 750, 1700, 7}};
    pid_t stress = -1;
    if (stage == 4) {
        pid_t parent = getpid();
        stress = fork();
        if (stress == 0) {
            if (prctl(PR_SET_PDEATHSIG, SIGTERM) != 0 || getppid() != parent) {
                _exit(1);
            }
            stress_loop();
            _exit(1);
        }
        check(stress < 0 ? errno : 0, "fork");
        fprintf(stderr, "Carga externa: processo PID %ld, mesma CPU\n", (long)stress);
    }
    if (stage >= 3) {
        for (unsigned i = 0; i < 2; ++i) {
            check(pthread_create(&workers[i], NULL, periodic_worker, &cfg[i]), "worker");
        }
    }
    if (stage >= 2) {
        check(pthread_create(&producer, NULL, event_source, NULL), "evento");
    }
    for (unsigned i = 1; i <= sample_count; ++i) {
        uint64_t start = 0;
        if (stage >= 2) {
            pthread_mutex_lock(&gate);
            while (requested != i) {
                pthread_cond_wait(&event, &gate);
            }
            start = release_ns;
            pthread_mutex_unlock(&gate);
        } else {
            if (coverage_cases) {
                fill_case(input, i);
            } else {
                fill_input(input, i);
            }
            start = monotonic_ns();
        }
        if (stage >= 3) {
            pthread_mutex_lock(&medium);
            hold_ns += shared[0];
            pthread_mutex_unlock(&medium);
        }
        bool valid = huffman_roundtrip(&huffman, input, sizeof input);
        elapsed[i - 1] = monotonic_ns() - start;
        invalid += !valid;
        if (stage >= 2) {
            pthread_mutex_lock(&gate);
            completed = i;
            pthread_cond_broadcast(&event);
            pthread_mutex_unlock(&gate);
        }
    }
    if (stress > 0) {
        kill(stress, SIGTERM);
        waitpid(stress, NULL, 0);
    }
    atomic_store(&stop, true);
    if (stage >= 2) {
        pthread_join(producer, NULL);
    }
    if (stage >= 3) {
        for (unsigned i = 0; i < 2; ++i) {
            pthread_join(workers[i], NULL);
        }
    }
    puts("ativacao,tempo_us");
    for (unsigned i = 0; i < sample_count; ++i) {
        printf("%u,%" PRIu64 ".%03" PRIu64 "\n", i + 1, elapsed[i] / 1000, elapsed[i] % 1000);
    }
    fprintf(stderr, "validas=%u invalidas=%u leituras=%" PRIu64 "\n",
            sample_count - invalid, invalid, hold_ns);
    free(elapsed);
    return invalid != 0;
}
