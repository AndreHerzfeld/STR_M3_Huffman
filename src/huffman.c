#include "huffman.h"
#include <string.h>

/* Active trees are kept in increasing frequency and then node order. */
static void insert_node(Huffman *w, uint8_t active[ALPHABET], unsigned size, uint8_t node)
{
    while (size > 0) {
        uint8_t before = active[size - 1];
        /* New node indices are strictly increasing, so existing ties stay first. */
        if (w->weight[before] <= w->weight[node]) {
            break;
        }
        active[size] = before;
        --size;
    }
    active[size] = node;
}

static void build_codes(Huffman *w, unsigned node, uint16_t code, unsigned width)
{
    if (node < ALPHABET) {
        w->code[node] = code;
        w->width[node] = width;
        return;
    }
    build_codes(w, w->left[node], code << 1, width + 1);
    build_codes(w, w->right[node], (code << 1) | 1u, width + 1);
}

/* The codec accepts 1..INPUT_SIZE symbols from 0..ALPHABET-1.
 * Every decoded symbol is compared, without short circuiting the traversal. */
bool huffman_roundtrip(Huffman *w, const uint8_t *input, size_t count)
{
    uint8_t active[ALPHABET];
    unsigned size = 0;
    memset(w->weight, 0, sizeof w->weight);
    for (size_t i = 0; i < count; ++i) {
        ++w->weight[input[i]];
    }
    for (unsigned symbol = 0; symbol < ALPHABET; ++symbol) {
        if (w->weight[symbol] != 0) {
            insert_node(w, active, size++, symbol);
        }
    }
    uint8_t next = ALPHABET;
    while (size > 1) {
        uint8_t first = active[0], second = active[1];
        w->left[next] = first;
        w->right[next] = second;
        w->weight[next] = w->weight[first] + w->weight[second];
        size -= 2;
        memmove(active, active + 2, size);
        insert_node(w, active, size++, next++);
    }
    uint8_t root = active[0];
    build_codes(w, root, 0, 0);
    if (root < ALPHABET) {
        /* A single symbol uses one zero bit per occurrence. */
        w->width[root] = 1;
    }
    size_t cursor = 0;
    for (size_t i = 0; i < count; ++i) {
        unsigned symbol = input[i];
        for (unsigned remaining = w->width[symbol]; remaining > 0; --remaining) {
            if ((cursor & 7u) == 0) {
                w->packed[cursor >> 3] = 0;
            }
            unsigned bit = (w->code[symbol] >> (remaining - 1)) & 1u;
            w->packed[cursor >> 3] |= bit << (7 - (cursor & 7u));
            ++cursor;
        }
    }
    size_t read = 0;
    unsigned differences = 0;
    for (size_t i = 0; i < count; ++i) {
        unsigned node = root;
        if (node < ALPHABET) {
            differences |= (w->packed[read >> 3] >> (7 - (read & 7u))) & 1u;
            ++read;
        }
        while (node >= ALPHABET) {
            unsigned bit = (w->packed[read >> 3] >> (7 - (read & 7u))) & 1u;
            node = bit ? w->right[node] : w->left[node];
            ++read;
        }
        differences |= node ^ input[i];
    }
    return (differences | (read ^ cursor)) == 0;
}
