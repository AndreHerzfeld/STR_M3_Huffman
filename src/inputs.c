#include "huffman.h"

void fill_input(uint8_t out[INPUT_SIZE], unsigned activation)
{
    uint32_t state = SEED ^ (UINT32_C(0x9e3779b9) * activation);
    for (unsigned i = 0; i < INPUT_SIZE; ++i) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        out[i] = state & (ALPHABET - 1);
    }
}

void fill_case(uint8_t out[INPUT_SIZE], unsigned test_case)
{
    for (unsigned i = 0; i < INPUT_SIZE; ++i) {
        switch (test_case) {
        case 1:
            out[i] = 3;
            break;
        case 2:
            out[i] = i % 2;
            break;
        case 3:
            out[i] = i % ALPHABET;
            break;
        case 4:
            out[i] = i < 1900 ? 0 : i % ALPHABET;
            break;
        default:
            fill_input(out, test_case - 4);
            return;
        }
    }
}
