# Huffman e tempo de resposta — UNIVALI, STR M3

Experimento em quatro cenários de carga. O Linux é a plataforma principal.
A ESP32 repete a campanha em FreeRTOS. Cada plataforma registra 13.000
ativações, com tempos em microssegundos.

## Reprodução

No Ubuntu, use GCC, gcov e Python 3 com Matplotlib. Na pasta do projeto:

```bash
bash ./rodar.sh --linux-only
```

Para repetir a coleta na ESP32, use também pyserial. Em um terminal com
o ESP-IDF ativo (a coleta usou a versão 6.1), conecte a placa por USB e rode:

```bash
bash ./rodar.sh --com-esp32
```

O coletor salva a flash original antes de gravar o firmware de teste e
tenta restaurá-la ao final. Mantenha a placa conectada durante a execução.
A configuração do firmware desativa o watchdog de tarefas para permitir
a etapa de estresse usada na coleta.

Os CSVs e a análise ficam em `resultados/`. Para recalcular a análise a
partir dos CSVs do ZIP de entrega, extraia o ZIP e rode:

```bash
python3 scripts/analyze.py /caminho/para/zip-extraido
```

`src/` contém a implementação em C e a instrumentação no Linux.
`esp32/` contém o firmware e a configuração usada na placa.
`scripts/` contém a coleta, a análise e a geração do relatório.
