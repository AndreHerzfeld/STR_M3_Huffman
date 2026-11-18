#ifndef TIMING_H
#define TIMING_H
#include <stdint.h>
#include <time.h>
#include <stdlib.h>

static inline uint64_t monotonic_ns(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        abort();
    }
    return UINT64_C(1000000000) * now.tv_sec + now.tv_nsec;
}
#endif
