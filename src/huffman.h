#ifndef HUFFMAN_H
#define HUFFMAN_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define INPUT_SIZE 2048
#define ALPHABET 16
#define SEED UINT32_C(20261118)

typedef struct {
    uint16_t weight[2 * ALPHABET - 1];
    uint8_t left[2 * ALPHABET - 1], right[2 * ALPHABET - 1];
    uint16_t code[ALPHABET];
    uint8_t width[ALPHABET];
    uint8_t packed[(INPUT_SIZE * (ALPHABET - 1) + 7) / 8];
} Huffman;

bool huffman_roundtrip(Huffman *workspace, const uint8_t *input, size_t count);
void fill_input(uint8_t out[INPUT_SIZE], unsigned activation);
void fill_case(uint8_t out[INPUT_SIZE], unsigned test_case);
#endif
