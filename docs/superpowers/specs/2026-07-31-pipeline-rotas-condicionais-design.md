# Pipeline com rotas condicionais (estilo n8n) — Design

Data: 2026-07-31

## Contexto e objetivo

O pipeline editável (`docs/superpowers/specs/2026-07-31-editable-pipeline-design.md`, já implementado)
trata as fases como uma sequência linear única — cada fase tem exatamente uma "próxima fase",
definida por `ordem`. Na prática, algumas fases têm mais de um desfecho possível: ex. "Criar
página" pode dar certo (segue pro fluxo normal) ou falhar (segue por um caminho alternativo, tipo
"gerar BM da forma convencional"). Objetivo: permitir que uma fase tenha múltiplas rotas de saída,
escolhidas manualmente pela pessoa ao avançar o perfil — como um editor de fluxo (n8n), mas com
decisão humana em vez de condição automática.

## Escopo decidido

- **Escolha manual da rota.** Não há avaliação automática de condição — ao clicar em "Avançar",
  se a fase atual tem mais de uma rota de saída, aparece um botão por rota (rotulado, ex: "Página
  criada" / "Falhou"); a pessoa clica na que aconteceu. Se a fase só tem uma rota, o comportamento
  é idêntico ao atual (um botão só).
- **Editor 100% no canvas.** A tela "Configurar pipeline" deixa de ser a lista com
  arrastar-pra-reordenar (construída e testada nesta mesma sessão) e vira um editor visual estilo
  n8n usando a biblioteca [Drawflow](https://github.com/jerosoler/Drawflow) (JS puro, sem
  dependências, via CDN — `cdn.jsdelivr.net/npm/drawflow@0.0.60/...`, mesmo padrão do SortableJS
  já usado). Criar fase, renomear, apagar E desenhar rota — tudo acontece no canvas, sem lista
  separada.
- **Mapa completo em todo lugar que hoje mostra o trilho.** No detalhe do perfil, o trilho de
  bolinhas vira o mesmo canvas em modo leitura, com o caminho que aquele perfil percorreu
  destacado. Na listagem (tabela densa), o trilho mini vira um botão "ver mapa" que abre esse
  mesmo mapa num modal.

## O que isso substitui do que já foi implementado

Fica: `PipelineStage` (campo `nome`), `PhaseHistory` (snapshot de texto imutável), a lógica de
"apagar fase realoca perfis com auditoria" (adaptada abaixo), o padrão de views
`login_required`/`require_POST`.

Sai: a tela de lista com drag-and-drop (SortableJS), a ideia de `ordem` como "próxima fase",
`Profile.proxima_fase`/`fase_index`/`fases_concluidas`/`fase_progress_percent` (dependiam de uma
sequência linear única — `fase_progress_percent` já não era usada em nenhum template, então sai
sem substituto), os templates `_pipeline_track.html`/`_advance_modal.html` no formato atual.

## Modelo de dados

### `PipelineStage` (alterações)

Adiciona `posicao_x` e `posicao_y` (`IntegerField`, posição do nó no canvas). `nome` continua
igual. `ordem` continua existindo só como critério estável de ordenação em listas/dropdowns/filtro
(não determina mais "próxima fase") — passa a ser preenchido automaticamente pela ordem de criação,
não editável pela pessoa.

### `PipelineRoute` (novo)

| Campo | Tipo | Notas |
|---|---|---|
| `origem` | FK → `PipelineStage` | `related_name='rotas_saida'` |
| `destino` | FK → `PipelineStage` | `related_name='rotas_entrada'`, `on_delete=PROTECT` (mesma rede de segurança do `Profile.fase_atual`) |
| `rotulo` | `CharField(max_length=100)` | Ex: "Padrão", "Falhou" |

`unique_together = ('origem', 'destino')` — no máximo uma rota entre o mesmo par de fases (evita
duas linhas ambíguas ligando os dois mesmos nós).

Uma fase com 0 rotas de saída é uma fase terminal (pode haver mais de uma agora). Uma fase com 1
rota se comporta como hoje. Uma fase com 2+ rotas exige escolha manual ao avançar.

### `PhaseHistory` (alterações)

Adiciona `fase_stage` (`FK → PipelineStage`, `null=True`, `on_delete=SET_NULL`) **além** do
`fase_nome` que já existe. `fase_nome` continua sendo o registro histórico imutável (o que é
exibido — nunca muda mesmo que a fase seja renomeada/apagada depois). `fase_stage` é um ponteiro
best-effort só pra saber *qual nó exatamente* foi visitado, usado para destacar o caminho no mapa;
se a fase referenciada for apagada depois, `fase_stage` vira `NULL` automaticamente e aquele ponto
do mapa simplesmente não é destacado — não quebra nada, só perde o destaque visual daquele passo
específico.

### `Profile` (alterações de comportamento, mesmos campos)

- `is_concluido` → `not self.fase_atual.rotas_saida.exists()`.
- `proxima_fase` (singular) é removido. Novo: `rotas_disponiveis` (property, retorna
  `self.fase_atual.rotas_saida.select_related('destino')`).
- `fase_index`/`fases_concluidas`/`fase_progress_percent` são removidos (não fazem mais sentido
  sem uma sequência linear única; nenhum deles tem um "próximo passo" bem definido num grafo com
  ramificações, e o segundo já não era usado em nenhum template).
- `avancar_fase(self, destino, usuario=None, observacao='')`: agora recebe explicitamente qual
  `PipelineStage` de destino foi escolhido. Valida que `destino` está entre
  `self.fase_atual.rotas_saida.values_list('destino', flat=True)` (nunca aceita um pulo
  arbitrário fora das rotas configuradas). Atualiza `fase_atual`, grava `PhaseHistory` com
  `fase_nome=destino.nome` e `fase_stage=destino`.

## Regras de negócio

### Avançar fase com múltiplas rotas

`profile_advance_phase` (view) passa a exigir um `destino` (pk da fase) no POST. O template do
modal de avançar itera `perfil.rotas_disponiveis`: se só tem uma, mostra um botão só ("Avançar",
igual hoje); se tem mais de uma, mostra um botão por rota, rotulado com `rota.rotulo`. Em ambos os
casos o POST já vem com o `destino` explícito — a view não precisa mais decidir nada, só validar.

### Exclusão de fase com perfis

Diferente de hoje (que movia automaticamente pra "fase anterior" — conceito que não existe mais
num grafo com ramificações): ao apagar uma fase que tem perfis nela, a pessoa escolhe manualmente,
num dropdown dentro do próprio fluxo de exclusão no canvas, para qual fase esses perfis devem ir
(lista de todas as outras fases existentes). Cada perfil movido gera uma entrada normal em
`PhaseHistory` (com `fase_stage` apontando pro destino escolhido), com observação de sistema
indicando que foi um movimento automático por remoção de fase — mesmo padrão de auditoria de hoje,
só que o destino agora é escolhido por humano em vez de inferido pela ordem.

Rotas que apontavam para a fase apagada (como `destino`) são removidas junto (CASCADE via FK).

## Editor no canvas ("Configurar pipeline")

Tela única, canvas Drawflow ocupando a área de conteúdo, com uma barra de ferramentas simples
("+ Nova fase"). Ao carregar, os dados de `PipelineStage`+`PipelineRoute` são serializados como
JSON no contexto da view e importados no Drawflow (`editor.import(...)`) — cada fase vira um nó
posicionado em `(posicao_x, posicao_y)`, cada rota vira uma conexão rotulada.

- **Criar fase**: botão da toolbar cria um nó novo em uma posição padrão; o nome é editável desde
  a criação (campo de texto dentro do próprio nó).
- **Renomear**: clique duplo no nome do nó → vira campo de texto → ao perder o foco, salva.
- **Apagar fase**: botão de lixeira no próprio nó. Se a fase tiver perfis, abre um diálogo pedindo
  a fase de destino (ver regra acima) antes de confirmar.
- **Mover fase**: arrastar o nó persiste a nova posição (`posicao_x`/`posicao_y`) ao soltar.
- **Criar rota**: arrastar uma conexão de uma borda de fase até outra abre um campo pequeno pra
  digitar o rótulo (texto livre, ex: "Padrão", "Falhou").
- **Apagar rota**: selecionar a conexão e apagar (interação nativa do Drawflow).

Todas essas ações viram chamadas `fetch()` para endpoints que respondem em **JSON** (não mais
redirect+mensagem Django) — um recarregamento de página destruiria o estado do canvas a cada
clique. As views de criar/renomear/apagar fase (já existentes) são adaptadas desse formato
formulário+redirect para JSON; a lógica de validação interna (nome obrigatório, etc.) não muda.

Novas views: `pipeline_stage_move` (persiste x/y), `pipeline_route_create`, `pipeline_route_delete`.

## Mapa somente leitura (detalhe do perfil + listagem)

O mesmo canvas Drawflow é reaproveitado em modo leitura (`editor.editor_mode = 'view'`, sem
arrastar/editar) para exibir o pipeline completo com o caminho do perfil destacado:

- **Detalhe do perfil**: substitui o trilho de bolinhas atual. Os nós/conexões que aparecem em
  `perfil.historico_fases` (via `fase_stage`, em ordem cronológica) ficam marcados como
  percorridos; a fase atual pulsa em âmbar, igual à identidade visual de hoje.
- **Listagem de perfis**: o trilho mini de cada linha vira um ícone/botão "ver mapa". Em vez de
  renderizar um canvas por linha (pesado com muitos perfis), existe um único modal compartilhado
  na página; ao clicar no botão de um perfil, um fetch busca os dados de traversal daquele perfil
  específico (novo endpoint JSON) e o canvas é desenhado dentro do modal sob demanda.

## Testes

- Fase com 1 rota: avançar funciona como hoje (um botão, POST com destino implícito na única
  rota).
- Fase com 2+ rotas: modal mostra um botão por rota; avançar por cada uma delas move
  corretamente e grava `PhaseHistory` com `fase_stage` certo.
- `avancar_fase` rejeita um `destino` que não é uma rota configurada a partir da fase atual.
- Fase sem rotas de saída: `is_concluido` é `True`.
- Apagar fase com perfis: perfis vão para o destino escolhido manualmente, com entrada de
  auditoria e `fase_stage` apontando pro destino.
- Apagar fase referenciada por `fase_stage` de entradas de histórico antigas: `fase_stage` vira
  nulo nessas entradas, `fase_nome` (texto) permanece intacto.
- Apagar fase remove as rotas que a referenciavam (origem ou destino).
- Criar/mover/apagar rota e fase via os novos endpoints JSON retorna os dados esperados e persiste
  no banco.
- Endpoint de traversal do perfil retorna a lista ordenada de fases/rotas percorridas.
