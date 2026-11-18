#include "huffman.h"
#include "timing.h"
#include "esp_chip_info.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include <inttypes.h>
#include <stdio.h>

enum { SHORT_COUNT = 1000, LONG_COUNT = 10000, EVENT_MS = 5, TEST_CORE = 0 };
static unsigned stage;
static Huffman huffman;
static uint8_t input[INPUT_SIZE];
static uint32_t elapsed[LONG_COUNT], shared[512];
static volatile uint32_t stress_memory[8192];
static TaskHandle_t producer, consumer, workers[2], stress;
static SemaphoreHandle_t medium;
static uint64_t release_ns;
static unsigned index_sample, invalid, stress_index;

struct worker_config { unsigned period_ms, hold_us, offset_ms, rate; };
static const struct worker_config config[] = {{7, 380, 2, 1}, {13, 850, 3, 7}};

static void take_sample(unsigned index, uint64_t start)
{
    if (stage >= 3) {
        xSemaphoreTake(medium, portMAX_DELAY);
        shared[0] += 1;
        xSemaphoreGive(medium);
    }
    bool valid = huffman_roundtrip(&huffman, input, sizeof input);
    uint64_t duration = (monotonic_ns() - start) / 1000;
    if (duration > UINT32_MAX) {
        abort();
    }
    elapsed[index] = duration;
    invalid += !valid;
}

static void event_consumer(void *arg)
{
    (void)arg;
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        take_sample(index_sample, release_ns);
        xTaskNotifyGive(producer);
    }
}

static void periodic_worker(void *arg)
{
    const struct worker_config *cfg = arg;
    vTaskDelay(pdMS_TO_TICKS(cfg->offset_ms));
    TickType_t previous = xTaskGetTickCount();
    for (;;) {
        xSemaphoreTake(medium, portMAX_DELAY);
        uint64_t until = monotonic_ns() + cfg->hold_us * UINT64_C(1000);
        unsigned index = 0;
        do {
            shared[index++ & 511] += cfg->rate;
        } while (monotonic_ns() < until);
        xSemaphoreGive(medium);
        if (xTaskDelayUntil(&previous, pdMS_TO_TICKS(cfg->period_ms)) == pdFALSE) {
            previous = xTaskGetTickCount();
        }
    }
}

static void external_worker(void *arg)
{
    (void)arg;
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        uint64_t until = monotonic_ns() + UINT64_C(720000);
        do {
            stress_index = (stress_index + 16) & 8191;
            stress_memory[stress_index] = stress_memory[stress_index] * 1664525u + 1013904223u;
        } while (monotonic_ns() < until);
    }
}

static void external_timer(void *arg)
{
    xTaskNotifyGive((TaskHandle_t)arg);
}

static void start_task(TaskFunction_t function, const char *name, void *arg,
                       UBaseType_t priority, TaskHandle_t *handle)
{
    BaseType_t result = xTaskCreatePinnedToCore(function, name, 4096, arg,
                                              priority, handle, TEST_CORE);
    if (result != pdPASS) {
        abort();
    }
}

static uint32_t crc_word(uint32_t crc, uint32_t word)
{
    for (unsigned byte = 0; byte < 4; ++byte) {
        crc ^= (word >> (8 * byte)) & 255u;
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ ((crc & 1u) ? UINT32_C(0xedb88320) : 0u);
        }
    }
    return crc;
}

static void run_stage(unsigned count)
{
    esp_timer_handle_t timer = NULL;
    invalid = 0;
    if (stage >= 2) {
        start_task(event_consumer, "huffman", NULL, 4, &consumer);
    }
    if (stage >= 3) {
        for (unsigned i = 0; i < 2; ++i) {
            start_task(periodic_worker, i ? "periodica13" : "periodica7",
                       (void *)&config[i], i ? 3 : 5, &workers[i]);
        }
    }
    if (stage == 4) {
        start_task(external_worker, "carga_externa", NULL, 6, &stress);
        const esp_timer_create_args_t args = {
            .callback = external_timer, .arg = stress, .name = "carga_2300us",
        };
        ESP_ERROR_CHECK(esp_timer_create(&args, &timer));
        ESP_ERROR_CHECK(esp_timer_start_periodic(timer, 2300));
    }
    TickType_t previous = xTaskGetTickCount();
    for (unsigned i = 0; i < count; ++i) {
        fill_input(input, i + 1);
        if (stage >= 2) {
            if (xTaskDelayUntil(&previous, pdMS_TO_TICKS(EVENT_MS)) == pdFALSE) {
                previous = xTaskGetTickCount();
                vTaskDelay(pdMS_TO_TICKS(EVENT_MS));
                previous = xTaskGetTickCount();
            }
            index_sample = i;
            release_ns = monotonic_ns();
            xTaskNotifyGive(consumer);
            ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        } else {
            take_sample(i, monotonic_ns());
            if ((i % 32) == 31) {
                vTaskDelay(1); /* Let the idle task run between activations. */
            }
        }
    }
    if (timer) {
        ESP_ERROR_CHECK(esp_timer_stop(timer));
        ESP_ERROR_CHECK(esp_timer_delete(timer));
        vTaskDelete(stress);
    }
    if (stage >= 3) {
        for (unsigned i = 0; i < 2; ++i) {
            vTaskDelete(workers[i]);
        }
    }
    if (stage >= 2) {
        vTaskDelete(consumer);
    }
    printf("STR_BEGIN,%u,%u\n", stage, count);
    uint32_t crc = UINT32_MAX;
    for (unsigned i = 0; i < count; ++i) {
        printf("STR_ROW,%u,%" PRIu32 "\n", i + 1, elapsed[i]);
        crc = crc_word(crc_word(crc, i + 1), elapsed[i]);
    }
    printf("STR_END,%u,%u,%u,%08" PRIx32 "\n", stage, count, invalid, ~crc);
    fflush(stdout);
}

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(3500));
    setvbuf(stdout, NULL, _IOLBF, 0);
    esp_chip_info_t chip;
    esp_chip_info(&chip);
#ifdef CONFIG_FREERTOS_UNICORE
    unsigned scheduler_cores = 1;
#else
    unsigned scheduler_cores = chip.cores;
#endif
    printf("STR_META,%s,%u,%u,%u,%u,%u,%u,%u\n", esp_get_idf_version(),
           (unsigned)chip.cores, scheduler_cores, (unsigned)chip.revision,
           (unsigned)configTICK_RATE_HZ, (unsigned)CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ,
           (unsigned)INPUT_SIZE, (unsigned)SEED);
    producer = xTaskGetCurrentTaskHandle();
    /* The main task and workers are all placed on core 0. */
    for (stage = 1; stage <= 4; ++stage) {
        medium = xSemaphoreCreateMutex();
        if (!medium) {
            abort();
        }
        run_stage(stage == 4 ? LONG_COUNT : SHORT_COUNT);
        vSemaphoreDelete(medium);
        vTaskDelay(pdMS_TO_TICKS(150));
    }
    puts("STR_DONE");
    fflush(stdout);
}
