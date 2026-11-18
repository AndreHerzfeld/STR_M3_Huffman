"""Eight-page report whose numeric statements come from the analyzed CSV files."""
import json
from textwrap import wrap

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

from analyze import LABELS, K_VALUES, fmt

INK = "#162940"
MUTED = "#486176"
ACCENT = "#087a82"
PAGE_WIDTH, PAGE_HEIGHT = 8.27, 11.69


class Page:
    def __init__(self, pdf, number, title, caption):
        self.pdf = pdf
        self.fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT), facecolor="white")
        self.fig.add_artist(Rectangle((.074, .948), .852, .004, transform=self.fig.transFigure,
                                      color=ACCENT, linewidth=0))
        self.text(.074, .965, "UNIVALI  /  ENGENHARIA DE COMPUTAÇÃO  /  SISTEMAS EM TEMPO REAL",
                  8, ACCENT, "bold")
        self.text(.074, .918, title, 22, INK, "bold")
        self.text(.074, .877, caption, 10.5, MUTED)
        self.text(.074, .042, "Atividade complementar M3  ·  Medição de tempo de resposta", 8, MUTED)
        self.text(.892, .042, f"{number:02d} / 08", 8, ACCENT, "bold")
        self.y = .833

    def text(self, x, y, value, pts=10, color=INK, weight="normal", url=None):
        return self.fig.text(x, y, str(value), color=color, fontsize=pts, va="top",
                             fontweight=weight, url=url)

    def heading(self, value):
        self.text(.074, self.y, value, 11.2, ACCENT, "bold")
        self.y -= .022

    def para(self, value, width=97, pts=9.7, gap=.016):
        for line in wrap(value, width=width, break_long_words=False, break_on_hyphens=False):
            self.text(.074, self.y, line, pts)
            self.y -= .016
        self.y -= gap

    def table(self, columns, rows, height, widths=None, fontsize=8.3):
        ax = self.fig.add_axes([.074, self.y - height, .852, height])
        ax.set_axis_off()
        t = ax.table(cellText=rows, colLabels=columns, colWidths=widths,
                     cellLoc="left", colLoc="left", bbox=[0, 0, 1, 1])
        t.auto_set_font_size(False)
        t.set_fontsize(fontsize)
        for (row, _), cell in t.get_celld().items():
            cell.set_edgecolor("white")
            cell.PAD = .075
            if not row:
                cell.set_facecolor("#1e455c")
                cell.get_text().set_color("white")
                cell.get_text().set_weight("bold")
            else:
                cell.set_facecolor("#eef5f8" if row % 2 else "#f7fafb")
                cell.get_text().set_color(INK)
        self.y -= height + .019

    def chart(self, path, height):
        ax = self.fig.add_axes([.069, self.y - height, .862, height])
        ax.imshow(plt.imread(path))
        ax.set_axis_off()
        self.y -= height + .015

    def close(self):
        if self.y < .057:
            raise ValueError(f"Conteúdo abaixo da área do relatório: {self.y:.3f}")
        self.pdf.savefig(self.fig)
        plt.close(self.fig)


def basic_stats(rows):
    for i, lines, branches, n, low, avg, hwm, hwm99, meet, s, m10, m20, m50 in rows:
        cover = "—" if lines == "" else f"{lines:.0f}/{branches:.0f}"
        yield [f"{i}. {LABELS[i-1]}", cover, str(n), fmt(low * 1000), fmt(avg * 1000),
               fmt(hwm * 1000), fmt(hwm99 * 1000), pct(meet), skip(s),
               str(m10), str(m20), str(m50)]


def pct(p):
    return f"{p:.2f}".replace(".", ",")


def skip(s):
    return "—" if s is None else str(s)


def stage_meta(path):
    return json.loads((path / "plataforma.json").read_text())


def top_processes(path, stage):
    file = path / f"processos_etapa{stage}_antes.txt"
    if not file.exists():
        return "registro indisponível"
    names = []
    for line in file.read_text().splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 7 and fields[1] not in names:
            names.append(fields[1])
        if len(names) == 6:
            break
    return ", ".join(names)


def make_report(run, linux, esp):
    root = run / "linux"
    analysis = root / "analise"
    ident = json.loads((run / "identificacao.json").read_text())
    host = stage_meta(root)
    rows = list(basic_stats(linux["tabela"]))
    fixed = linux["D_fixo_ns"]
    stats = linux["estatisticas"]
    losses = linux["perdas"]
    n_last = stats[-1]["n"]
    with PdfPages(run / "Relatorio_STR_M3.pdf", metadata={
        "Title": "Quanto o teste enxerga do pior caso?",
        "Author": ident["nome"] or "Identificação pendente",
        "Subject": "Huffman, tempo de resposta e comportamento (m,k)-firme",
    }) as pdf:
        p = Page(pdf, 1, "Quanto o teste enxerga do pior caso?",
                 "Codificação de Huffman  ·  Cobertura, HWM e perdas de deadline")
        p.heading("Identificação")
        p.para(f'{ident["nome"] or "[PREENCHER NOME COMPLETO]"}    |    '
               f'RA {ident["ra"] or "[PREENCHER RA]"}    |    Trabalho individual')
        repo = ident["repositorio"]
        p.text(.074, p.y, repo or "[PREENCHER LINK COMPARTILHADO DO REPOSITÓRIO]",
               pts=9.3, color=ACCENT, url=repo or None)
        p.y -= .042
        p.heading("Pergunta experimental")
        p.para("A medição procura separar a corretude lógica do comportamento temporal. Cada etapa "
               "executa a mesma tarefa Huffman, mas amplia o escopo de interação e expõe novas "
               "oportunidades de espera, preempção e contenção. A segunda pergunta é quantos "
               "prazos podem ser perdidos localmente em uma sequência de ativações.")
        p.heading("Plataforma principal")
        p.para(f'{host["so"]} · kernel {host["kernel"]}. CPU {host["cpu"]}. '
               f'Núcleos físicos {host["nucleos_fisicos"] or "indisponíveis"} e '
               f'{host["cpus_logicas"]} CPUs lógicas visíveis ao SO. '
               f'CPU lógica do teste {host["cpu_teste"]}. Governor dessa CPU '
               f'{host["governor_cpu_teste"] or "indisponível no sysfs"}. '
               f'Política {host["classe_politica"] or host["politica"]}. '
               f'Compilador {host["compilador"]}. Coleta em {host["data_local"][:16].replace("T", " ")} '
               f'(hora local da máquina).')
        p.para(f'Processos com maior CPU média registrados antes das etapas 1 e 4, respectivamente: '
               f'{top_processes(root, 1)}; {top_processes(root, 4)}. '
               'Os registros completos de processos por etapa e da carga do host acompanham os CSVs.')
        p.heading("Dados e validação")
        p.para("Cada vetor contém 2.048 símbolos de oito bits do alfabeto 0–15. O gerador xorshift32 "
               "usa a semente 20.261.118 e inicialização por índice, fazendo a ativação i receber "
               "o mesmo vetor em cada etapa e plataforma. A implementação constrói a árvore, grava "
               "o código em bits e decodifica para comparar símbolo a símbolo e verificar o "
               "comprimento. Uma divergência invalida a execução.")
        if esp:
            device = stage_meta(run / "esp32")
            p.heading("Repetição embarcada")
            p.para(f'{device["alvo"]}, revisão {device["revisao"]}, ESP-IDF {device["idf"]}, FreeRTOS '
                   f'com {device["nucleos_escalonador"]} núcleo(s) de escalonamento e '
                   f'{device["nucleos_fisicos"]} no chip. Frequência configurada em '
                   f'{device["frequencia_mhz"]} MHz e tick de {device["tick_hz"]} Hz. '
                   f'{device["programas"]}')
        elif ident["esp32_solicitada"]:
            p.heading("Campanha opcional")
            p.para("A campanha embarcada ficou incompleta. A tabela e as conclusões usam a campanha "
                   "Linux. O diagnóstico do coletor acompanha os dados.")
        p.close()

        p = Page(pdf, 2, "Casos, procedimento e critérios",
                 "O fim da resposta é marcado imediatamente após a validação.")
        p.para("As etapas 1 a 3 têm pelo menos 1.000 ativações cada. A etapa 4 tem pelo menos "
               "10.000. A geração do vetor antecede a liberação, e a escrita dos CSVs ocorre "
               "após a medição. A instrumentação usa clock_gettime(CLOCK_MONOTONIC).")
        methodology = [
            ("1. Tarefa isolada", "Caso. Huffman recebe vetores aleatórios determinísticos, sem carga "
             "controlada concorrente. Procedimento. Gerar o vetor, ler o relógio, codificar, "
             "decodificar, validar e ler o relógio novamente. Critério. Todas as saídas devem bater "
             "com a entrada, e todas as ativações devem ter registro. Os testes de cobertura "
             "adicionam vetores constante, alternado, uniforme e enviesado."),
            ("2. Comportamental", "Caso. Um evento externo à tarefa por vez, sem concorrentes "
             "experimentais. Procedimento. Um produtor periódico prepara o vetor e registra a "
             "liberação antes de acordar Huffman por condição POSIX no Linux ou notificação no "
             "FreeRTOS. O produtor aguarda confirmação. Critério. Exatamente uma resposta válida "
             "por evento, incluindo despacho e execução no tempo de resposta."),
            ("3. Intertarefas", "Caso. Huffman e dois concorrentes periódicos compartilham um mutex "
             "na mesma CPU. Procedimento. Manter a fonte de eventos e executar concorrentes a "
             "cada 3,7 e 7,1 ms no Linux, com seções de 330 e 750 µs e taxas de atualização "
             "diferentes. Na ESP32, 7 e 13 ms, com seções de 380 e 850 µs. Critério. Validar "
             "Huffman em toda ativação, medindo a espera pelo mutex e possíveis preempções."),
            ("4. Sistema", "Caso. Preservar eventos e contenção e somar carga independente. "
             "Procedimento. No Linux, iniciar um processo na mesma CPU que percorre continuamente "
             "4 MiB de memória. Na placa, um timer periódico de 2,3 ms libera uma tarefa de alta "
             "prioridade que acessa 32 KiB por até aproximadamente 720 µs por ativação. "
             "A carga disputa CPU e memória com o conjunto. Critério. Registrar cauda e perdas "
             "com a validação lógica preservada e sem mudar o prazo fixo."),
        ]
        for title, block in methodology:
            p.heading(title)
            p.para(block, gap=.007)
        p.heading("Deadline de referência")
        p.para(f'D = 1,20 × HWM da etapa 1 = {fmt(fixed)} µs no Linux, arredondado para cima ao ns. '
               'O mesmo prazo vale nas quatro etapas dessa plataforma. A ativação cumpre o prazo '
               'se o tempo for menor ou igual a D. A etapa 2 em diante usa período nominal de '
               '2,5 ms no Linux e 5 ms no FreeRTOS. Uma ativação pendente é admitida por vez, '
               'com reprogramação da próxima liberação após um estouro do período.')
        p.close()

        p = Page(pdf, 3, "Estatísticas, cobertura e margem", f"Campanha Linux · D fixo de {fmt(fixed)} µs")
        p.table(["Etapa", "Lin./desv.\n(%)", "n", "Mín.\n(µs)", "Média\n(µs)", "HWM\n(µs)",
                 "HWM99\n(µs)", "No prazo\n(%)", "S", "m\n10", "m\n20", "m\n50"],
                rows, .145, [.188, .091, .066, .083, .083, .093, .09, .095, .039, .055, .055, .055],
                fontsize=7.1)
        p.para("HWM99 retira os ⌊n/100⌋ maiores valores e toma o maior dos restantes. S é a menor "
               "distância em ativações entre perdas. O símbolo — indica S indefinido com menos "
               "de duas perdas. As três colunas m completam os pares (m,10), (m,20) e (m,50).",
               pts=9.1, gap=.01)
        p.heading("Experimento A · cobertura versus tempo")
        coverage = linux["cobertura"]
        if coverage:
            full = coverage["primeiro_prefixo_completo"]
            trials = coverage["prefixos_dirigidos"]
            crows = [[size, f'{record["linhas"][0]}/{record["linhas"][1]}',
                      f'{record["desvios"][0]}/{record["desvios"][1]}',
                      fmt(record["hwm_us"] * 1000)] for size, record in trials.items()]
            p.table(["Casos acumulados", "Linhas executadas", "Desvios tomados", "HWM (µs)"],
                    crows, .122)
            if full:
                statement = f'Cobertura completa no prefixo {full}, com HWM de {fmt(trials[full]["hwm_us"]*1000)} µs.'
            else:
                last = trials[str(len(trials))]
                statement = (f'Cobertura abaixo de 100%. As linhas e desvios remanescentes aparecem no '
                             f'gcov bruto. Linhas com desvios remanescentes: {last["linhas_com_desvios_nao_cobertos"]}.')
            comparison = ", ".join(fmt(s["hwm_ns"]) for s in stats[1:])
            p.para(statement + f" Os HWM das etapas 2, 3 e 4 foram, em ordem, {comparison} µs. "
                   "A síntese usa o ensaio dirigido na etapa 1 quando completo e cobertura de "
                   "reexecuções aleatórias nas demais etapas. A comparação temporal "
                   "principal usa a campanha sem gcov, para limitar o efeito da instrumentação.",
                   pts=9.1, gap=.008)
        rising = all(left["hwm_ns"] < right["hwm_ns"] for left, right in zip(stats, stats[1:]))
        p.para(("O HWM aumentou a cada etapa. " if rising else "O HWM não cresceu estritamente em todas as etapas. ")
               + "Os máximos podem variar com fase entre tarefas, preempções, cache, carga e amostragem. "
               "A cobertura contabiliza linhas e desvios do código Huffman. Esses contadores não "
               "enumeram todos os caminhos completos nem as condições temporais de execução.",
               pts=9.1, gap=.008)
        p.heading("Experimento C · margem sobre o HWM isolado")
        p.table(["Margem", "Limite (µs)", "HWM sistema (µs)", "Etapas acima do limite"],
                [[f"{pc}%", fmt(d), fmt(stats[-1]["hwm_ns"]), ", ".join(map(str, bad)) or "Nenhuma"]
                 for pc, d, bad in linux["margens"]], .105, fontsize=8.3)
        p.para("O exemplo de aula de 12–14 ms versus 10–16 ms mostra que a faixa pode crescer "
               "mesmo com centros parecidos. A margem sobre a etapa isolada precisa ser julgada "
               "pela mudança da cauda e pelo estresse efetivamente medido.", pts=9.1, gap=.006)
        p.close()

        p = Page(pdf, 4, "Distribuições e cauda",
                 "Histogramas por etapa · eixo de tempo e contagem em escala logarítmica")
        p.chart(analysis / "histogramas.png", .474)
        p.table(["Etapa", "Mediana (µs)", "HWM − HWM99 (µs)", "HWM / mediana"],
                [[LABELS[i], fmt(s["mediana_ns"]), fmt(s["hwm_ns"] - s["hwm99_ns"]),
                  f'{s["hwm_ns"]/s["mediana_ns"]:.2f}×'.replace(".", ",")]
                 for i, s in enumerate(stats)], .121)
        tail = max(range(4), key=lambda i: stats[i]["hwm_ns"] / stats[i]["mediana_ns"])
        p.para(f'A mediana situa a região central. A maior separação relativa entre centro e extremo '
               f'ocorre na etapa {tail + 1} ({LABELS[tail]}). A zona sombreada marca valores acima '
               'do HWM99 e contém no máximo 1% da amostra. A distância até a marca de HWM '
               'mostra a extensão dessa cauda. O prazo fixo permite ver quais classes de resposta '
               'podem atravessar o limite.')
        p.close()

        p = Page(pdf, 5, "Tempos por ativação",
                 "As marcas destacam respostas estritamente acima do HWM99 de cada etapa.")
        p.chart(analysis / "tempos.png", .493)
        p.table(["Etapa", "Ativação do HWM", "Picos isolados", "Grupos de picos", "Rajadas de perdas"],
                [[LABELS[i], s["hwm_pos"], s["picos"]["isolados"], s["picos"]["grupos"], loss["rajadas"]]
                 for i, (s, loss) in enumerate(zip(stats, losses))], .123)
        isolated_word = "não foram observadas rajadas" if not losses[-1]["rajadas"] else (
            f'foram observadas {losses[-1]["rajadas"]} rajadas, '
            f'com até {losses[-1]["maior_rajada"]} perdas consecutivas')
        p.para(f'Na etapa 4, {isolated_word} para o D fixo. A definição de pico usa '
               'a cauda da própria etapa. Dois picos adjacentes ou mais formam um grupo. '
               'A linha de D indica quais ativações perderam o prazo. Grupos de picos e '
               'rajadas de perdas podem ocorrer em intervalos diferentes.')
        p.close()

        p = Page(pdf, 6, "Convergência do HWM",
                 "Experimento B · máximos acumulados preservando a ordem das ativações")
        p.chart(analysis / "convergencia.png", .252 if esp else .355)
        p.table(["Etapa", "10", "20", "100", "1.000", "10.000"],
                [[LABELS[i], *[fmt(v) for v in marks], *(["—"] * (5 - len(marks)))]
                 for i, marks in enumerate(linux["marcos"])], .119)
        marks = linux["marcos"][-1]
        p.para(f'Na etapa 4 o primeiro máximo final apareceu na ativação {stats[-1]["hwm_pos"]} '
               f'de {n_last}. Com 10 ativações, o HWM era {fmt(marks[0])} µs e, com 20, '
               f'{fmt(marks[1])} µs. Os dois recortes ficaram '
               f'{pct(100*(1-marks[0]/stats[-1]["hwm_ns"]))}% e '
               f'{pct(100*(1-marks[1]/stats[-1]["hwm_ns"]))}% abaixo do máximo final, respectivamente. '
               'Trechos planos indicam ausência de novo recorde nas amostras observadas. Mais '
               'ativações ou fases distintas ainda podem elevar o máximo.')
        if esp:
            p.heading("Comparação com a ESP32")
            p.table(["Etapa", "HWM Linux (µs)", "HWM ESP32 (µs)", "No prazo ESP32 (%)", "ESP32 (m,20)"],
                    [[LABELS[i], fmt(stats[i]["hwm_ns"]), fmt(esp["estatisticas"][i]["hwm_ns"]),
                      pct(esp["perdas"][i]["percentual_no_prazo"]), f'({esp["perdas"][i]["m"][20]},20)']
                     for i in range(4)], .114, fontsize=8)
            p.para(f'A ESP32 tem D fixo próprio de {fmt(esp["D_fixo_ns"])} µs pela mesma regra. '
                   'Variam também o período de liberação, prioridades, memória e relógio. '
                   'A comparação é descritiva. Os gráficos e a análise completa da ESP32 estão no ZIP.',
                   pts=9, gap=.004)
        p.close()

        p = Page(pdf, 7, "Janelas deslizantes e perdas",
                 "O pior número de perdas em qualquer janela define o m observado para cada k.")
        p.chart(analysis / "janelas.png", .527)
        p.table(["Etapa", "Total de perdas", "S", "Pior k=10", "Pior k=20", "Pior k=50"],
                [[LABELS[i], round(stats[i]["n"] * (1 - r["percentual_no_prazo"] / 100)),
                  skip(r["skip_factor"]), *[r["maximo_perdas_por_janela"][k] for k in K_VALUES]]
                 for i, r in enumerate(losses)], .106)
        p.para("Janelas completas avançam uma ativação. Calcula-se m = k − máximo de perdas "
               "observado. A sequência de perdas, suas distâncias e as rajadas estão nos CSVs "
               "de cada etapa. S = 1 significa perdas consecutivas. O resultado (m,k)-firme "
               "descreve esta amostra. Uma execução futura pode produzir uma janela pior.",
               pts=9.1, gap=.005)
        p.close()

        p = Page(pdf, 8, "Variação de deadline e conclusão",
                 "Experimento D · recálculo das perdas nas etapas 3 e 4 do Linux")
        p.table(["Etapa", "D (µs)", "No prazo (%)", "S", "(m,20)", "Isoladas", "Rajadas", "Maior"],
                [[i, fmt(d), pct(meet), skip(s), f"({m},20)", isolated, burst, largest]
                 for i, d, meet, s, m, isolated, burst, largest in linux["D_cenarios"]],
                .158, fontsize=8.1)
        p.para("Os prazos alternativos usam o HWM da etapa 1, o HWM99 da etapa 4 e o "
               "ponto intermediário quando distinto. Caso haja coincidência, usa-se D fixo e, "
               "se preciso, um incremento de 1 µs. Os CSVs e gráficos do experimento D "
               "registram todas as janelas para k = 10, 20 e 50.", pts=9.2, gap=.008)
        goal = linux["D_meta"]
        p.heading("Menor D para a meta experimental (18,20)")
        p.para(f'O limite mínimo na etapa 4 é {fmt(goal["D_min_ns"])} µs. Em cada janela '
               'ordena-se o tempo e toma-se o 18º menor. O máximo desses valores é o menor D '
               f'que mantém a meta em todas as janelas medidas. Reduzir 1 ns produz m = '
               f'{goal["m_em_D_menos_1ns"]}. Usar o HWM de {fmt(goal["D_hwm_ns"])} µs cumpre 20/20 '
               'nas janelas observadas. A meta 18/20 foi adotada para este experimento e admite '
               'até duas perdas em 20 ativações.', pts=9.2, gap=.007)
        p.para("Em uma planta com inércia, o controle pode tolerar uma amostra perdida e se "
               "recuperar na seguinte. Várias perdas consecutivas prolongam o intervalo sem "
               "atualização. O mesmo percentual global admite padrões muito diferentes. A "
               "distância em ativações só equivale a tempo mediante uma cadência conhecida.",
               pts=9.2, gap=.008)
        p.heading("Ameaças à validade")
        p.para("Linux de propósito geral, interrupções, outros processos, cache e estados de "
               "energia afetam as medições. A afinidade e as cargas escolhidas restringem os "
               "entrelaçamentos observados. A leitura do relógio, a resolução do temporizador e "
               "a compilação gcov alteram a execução. Há fases de competição, entradas e cargas "
               "externas ainda por explorar. A amostra da etapa 4 é maior e tem mais oportunidades "
               "para observar extremos. O produtor com uma pendência não reproduz filas de chegada.",
               pts=9.2, gap=.008)
        p.heading("Conclusão")
        p.para("O teste dirigido avalia a lógica de Huffman. O HWM mede o maior tempo que a "
               "campanha conseguiu observar. O critério (m,k) torna verificável, sobre os dados, "
               "um limite para a concentração das perdas. Tanto o HWM quanto o par observado "
               "continuam dependentes das condições e da extensão da campanha.", pts=9.2, gap=.008)
        p.close()
