# Pipeline editável (motor de workflow simples) — Design

Data: 2026-07-31

## Contexto e objetivo

Hoje as 7 fases do fluxo de criação de contas são um `Phase(models.TextChoices)` fixo em
`profiles/models.py`, usado direto em `Profile.fase_atual`, no histórico de auditoria
(`PhaseHistory.fase`), no funil do dashboard, no filtro da listagem e no trilho visual
(`_pipeline_track.html`). Qualquer mudança na sequência de fases hoje exige editar código e
rodar uma migration.

Objetivo: permitir que qualquer usuário logado crie, renomeie, reordene e remova fases do
pipeline pela própria interface, sem precisar mexer em código.

## Escopo decidido

- **Um único pipeline editável**, global — não múltiplos workflows nomeados. Todo perfil segue
  a mesma sequência de fases, que passa a ser dinâmica em vez de fixa no código.
- **Sem controle de permissão por papel** — qualquer usuário logado pode editar a estrutura do
  pipeline, mesma regra que já vale pro resto do app hoje (não há distinção de staff/superuser
  nas views).
- **Sem branching/condições** — o pipeline continua sendo uma sequência linear, só que editável.
  Isso não é um workflow engine genérico com regras condicionais; é a lista de fases atual
  virando dado em vez de código.

## Modelo de dados

### `PipelineStage` (novo)

| Campo | Tipo | Notas |
|---|---|---|
| `nome` | `CharField` | Nome livre da fase (ex: "Verificação de página do Facebook") |
| `ordem` | `PositiveIntegerField` (unique) | Posição na sequência; substitui `Phase.ordered_values()` |

Métodos/propriedades: `class Meta: ordering = ['ordem']`.

### `Profile.fase_atual`

Passa de `CharField(choices=Phase.choices)` para `ForeignKey('PipelineStage', on_delete=PROTECT)`.
`on_delete=PROTECT` é uma rede de segurança — a lógica de exclusão de fase sempre move os
perfis afetados *antes* de apagar a fase (ver "Exclusão de fase com perfis"), então o PROTECT
nunca deveria disparar na prática; ele existe para nunca perder integridade referencial caso
algum caminho de código esqueça de mover os perfis primeiro.

As propriedades existentes do model (`fase_index`, `fases_concluidas`, `fase_progress_percent`,
`proxima_fase`) mudam de implementação (consultam `PipelineStage.objects.order_by('ordem')` em
vez de `Phase.ordered_values()`) mas mantêm a mesma assinatura e comportamento observável.
`is_concluido` passa a ser simplesmente `self.proxima_fase is None` (é a última fase da
sequência atual, não mais uma comparação com uma constante `CONCLUIDO`).

### `PhaseHistory.fase` → `PhaseHistory.fase_nome` (snapshot)

Hoje é `CharField(choices=Phase.choices)`. Passa a ser um `CharField` de **texto livre**,
gravado com o nome da fase *no momento da transição* (ex.: "3. Verificação de página do
Facebook"), sem FK para `PipelineStage`.

**Por quê**: um log de auditoria não pode mudar de significado depois do fato. Se o histórico
referenciasse `PipelineStage` por FK, renomear uma fase reescreveria silenciosamente o que o
histórico mostra para transições passadas, e apagar uma fase exigiria uma política de
`on_delete` (SET_NULL perderia a informação, CASCADE apagaria histórico real). Snapshot em
texto evita os dois problemas: o histórico é imutável por construção.

### Migração de dados

Uma migration de dados (`profiles/migrations/000X_...py`):
1. Cria os 7 `PipelineStage` atuais, na mesma ordem e com os mesmos nomes do `Phase` atual
   (ordem 1–7).
2. Para cada `Profile`, reaponta `fase_atual` (antes string) para o `PipelineStage`
   correspondente.
3. Para cada `PhaseHistory`, copia o valor textual do `fase` (via `get_fase_display()`) para o
   novo `fase_nome`.

Nenhum dado existente muda de posição ou se perde — é puramente uma migração de representação.

## Tela "Configurar pipeline"

Nova rota `profiles/pipeline/configurar/`, novo item na sidebar (`base.html`, junto de
Dashboard/Perfis/Novo perfil).

- Lista as fases na ordem atual. Cada linha tem: alça de arrastar, nome (editável inline via
  ícone de lápis → campo de texto), botão de apagar (lixeira).
- **Reordenar**: drag-and-drop. Ao soltar, dispara um POST assíncrono que persiste a nova ordem
  imediatamente — sem botão "Salvar" separado, consistente com a ação "Avançar fase" já ser
  imediata no resto do app.
- **Adicionar**: campo de texto + botão no fim da lista, sempre insere a nova fase na última
  posição.
- **Apagar**: abre modal de confirmação (reaproveitando o padrão visual do `_advance_modal.html`
  — backdrop com blur, ícone no header) avisando quantos perfis estão na fase agora e que serão
  movidos para a fase anterior. Se restar apenas 1 fase no pipeline, o botão de apagar fica
  desabilitado (pipeline nunca fica vazio).

## Exclusão de fase com perfis

Ao confirmar a exclusão de uma fase que tem perfis com `fase_atual` apontando pra ela:
- Todos esses perfis são movidos para a **fase anterior** (a de `ordem` imediatamente menor).
- **Caso de borda — apagar a primeira fase**: não existe "fase anterior". Os perfis afetados
  vão para a fase que **se tornará a primeira** depois da exclusão (a atual segunda fase).
- Cada movimentação automática gera uma entrada normal em `PhaseHistory` (mesma tabela de
  auditoria), atribuída ao usuário que executou a exclusão da fase (é ele quem causou o
  movimento), com uma observação do sistema indicando que foi um movimento automático por
  remoção de fase — para não haver uma lacuna silenciosa no histórico do perfil.

## Reflexos no restante do app

Trocam a fonte de dados de `Phase.choices`/`Phase.ordered_values()` para
`PipelineStage.objects.order_by('ordem')`, sem mudança de comportamento visual:
- `Profile.avancar_fase()` — próxima fase por `ordem`, não por lista estática.
- `profiles/context_processors.py::fases_ordenadas` — vira `PipelineStage.objects.all()`.
- `profiles/forms.py::ProfileFilterForm.fase` — vira `ModelChoiceField` sobre `PipelineStage`.
- `profiles/views.py::api_dashboard_data` (funil) — itera `PipelineStage` em vez de
  `Phase.choices`; usa `stage.ordem` diretamente pro rótulo numérico do eixo do gráfico em vez
  de extrair o número do texto do label (o parsing atual, `label.split('.')[0]`, quebra se o
  nome da fase não começar mais com "N. " depois de editado pelo usuário).
- `templates/profiles/_pipeline_track.html`, `_advance_modal.html` — trocam
  `fase_value.label` / `perfil.get_fase_atual_display` por `fase_value.nome` /
  `perfil.fase_atual.nome`.
- `profiles/admin.py` — `fase_atual` continua filtrável no Django admin (FK renderiza dropdown
  automaticamente); `PhaseHistoryInline` mostra `fase_nome` em vez de `fase`.

## Testes

- Reordenar fases via drag-and-drop persiste a nova `ordem`.
- Apagar fase do meio move perfis para a fase anterior corretamente, com entrada de auditoria.
- Apagar a primeira fase move perfis para a nova primeira fase.
- Não é possível apagar a última fase restante.
- `avancar_fase()` respeita a ordem dinâmica após reordenação.
- Renomear ou apagar uma fase não altera entradas já existentes em `PhaseHistory` (snapshot
  imutável).
- Migração de dados preserva `fase_atual` de cada perfil e o texto de cada entrada de histórico
  existente.
