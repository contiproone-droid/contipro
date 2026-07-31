# Pipeline com rotas condicionais — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the linear "next stage by `ordem`" pipeline with a branching graph: any `PipelineStage`
can have 0+ outgoing `PipelineRoute`s to other stages, chosen manually when advancing a profile.
Replace the drag-and-drop list editor with a Drawflow-based canvas editor (create/rename/delete
stages, draw/remove routes), and replace the dot-and-line pipeline track with a read-only version
of the same canvas, highlighting the path each profile actually traveled.

**Architecture:** `PipelineRoute(origem, destino, rotulo)` is the new source of truth for "what
comes next" — `PipelineStage.ordem` survives only as a stable secondary sort key for
dropdowns/admin, no longer meaningful as a sequence. `PhaseHistory` gains `fase_stage` (nullable
FK, best-effort pointer for highlighting) alongside its existing immutable `fase_nome` text
snapshot. The canvas editor and the read-only map both render the same JSON shape via Drawflow,
loaded from CDN (no build step, matching the rest of the app).

**Tech Stack:** Django 6.0 (existing). [Drawflow](https://github.com/jerosoler/Drawflow) 0.0.60 via
`cdn.jsdelivr.net/npm/drawflow@0.0.60/...` (dependency-free vanilla JS flow-chart library).

## Global Constraints

- **Manual route choice only** — no automatic condition evaluation. A stage with 1 outgoing route
  behaves exactly like today (single "Avançar" button); 2+ routes show one button per route.
- **The pipeline can never be empty** — same invariant as before, still enforced server-side.
- **`PhaseHistory.fase_nome` (text) never changes meaning** — it stays the immutable audit record.
  `fase_stage` (FK) is purely a best-effort pointer for the map visualization; it going `NULL` when
  a stage is later deleted must never affect what `fase_nome` displays.
- **Deleting a stage that has profiles on it requires an explicit destination** picked by the
  person deleting it — no more inferring "the previous stage" (doesn't exist in a graph).
- **This supersedes the linear editor shipped earlier this session** — `templates/profiles/
  pipeline_configure.html`'s drag-and-drop list, `Profile.proxima_fase`/`fase_index`/
  `fases_concluidas`/`fase_progress_percent`, `_pipeline_track.html`, and `PipelineStage.reordenar`/
  `pipeline_stage_reorder` are all removed as part of this plan, not kept alongside the new system.
- **Follow existing conventions**: `login_required`/`require_POST` on every mutating view,
  `ModelForm` for validated input, CSS inline in `templates/base.html`, CDN-only JS with SRI hashes
  on `<script>` tags (see `superpowers:writing-plans`' sibling plan for the SortableJS precedent —
  same pattern applies to the Drawflow tag).

---

## Task 1: Data model — `PipelineRoute`, `fase_stage`, branching-aware `Profile`/`PipelineStage`

**Files:**
- Modify: `profiles/models.py`
- Modify: `profiles/signals.py`
- Modify: `profiles/admin.py`
- Create: `profiles/migrations/0005_pipelineroute_and_fase_stage.py`
- Test: `profiles/tests.py`

**Interfaces:**
- Produces: `PipelineRoute(origem, destino, rotulo)` model (`related_name='rotas_saida'` /
  `'rotas_entrada'`). `PipelineStage.posicao_x`/`posicao_y` (`IntegerField`, default `0`).
  `PhaseHistory.fase_stage` (nullable FK). `Profile.rotas_disponiveis` (property, replaces
  `proxima_fase`). `Profile.is_concluido` (redefined). `Profile.avancar_fase(destino, usuario=None,
  observacao='')` (new required first arg). `PipelineStage.excluir_e_realocar(destino=None,
  usuario=None)` (new optional `destino` param, replaces automatic "fase anterior" inference).
  Removes: `Profile.fase_index`, `Profile.fases_concluidas`, `Profile.fase_progress_percent`,
  `Profile.proxima_fase`, `PipelineStage.reordenar`.

- [ ] **Step 1: Write failing tests**

Replace the now-obsolete linear-specific tests in `profiles/tests.py`'s `PipelineStageModelTests`
that reference the removed properties (`fase_index`, `fases_concluidas`, single-arg
`avancar_fase()`), and add new ones. Edit the class to:

```python
class PipelineStageModelTests(TestCase):
    def test_migration_seeds_seven_stages_in_order(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        self.assertEqual(len(stages), 7)
        self.assertEqual(stages[0].nome, '1. Perfil criado no AdsPower')
        self.assertEqual(stages[-1].nome, '7. Concluído / Ativo')

    def test_new_profile_defaults_to_first_stage(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        primeira = PipelineStage.objects.order_by('ordem').first()
        self.assertEqual(perfil.fase_atual, primeira)

    def test_stage_with_no_outgoing_route_is_terminal(self):
        stage = PipelineStage.objects.create(nome='Terminal', ordem=100)
        self.assertEqual(list(stage.rotas_saida.all()), [])
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=stage)
        self.assertTrue(perfil.is_concluido)
        self.assertEqual(list(perfil.rotas_disponiveis), [])

    def test_avancar_fase_com_uma_rota(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=101)
        destino = PipelineStage.objects.create(nome='Destino', ordem=102)
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)

        avancou = perfil.avancar_fase(destino)
        perfil.refresh_from_db()

        self.assertTrue(avancou)
        self.assertEqual(perfil.fase_atual, destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()
        self.assertEqual(entrada.fase_nome, 'Destino')
        self.assertEqual(entrada.fase_stage, destino)

    def test_avancar_fase_rejeita_destino_fora_das_rotas_configuradas(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=103)
        destino_valido = PipelineStage.objects.create(nome='Válido', ordem=104)
        destino_invalido = PipelineStage.objects.create(nome='Inválido', ordem=105)
        PipelineRoute.objects.create(origem=origem, destino=destino_valido, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)

        self.assertFalse(perfil.avancar_fase(destino_invalido))
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, origem)

    def test_renomear_fase_nao_altera_historico_existente(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=106)
        destino = PipelineStage.objects.create(nome='Destino', ordem=107)
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)
        perfil.avancar_fase(destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()

        destino.nome = 'Renomeado'
        destino.save(update_fields=['nome'])
        entrada.refresh_from_db()

        self.assertEqual(entrada.fase_nome, 'Destino')
        self.assertEqual(entrada.fase_stage, destino)

    def test_apagar_fase_referenciada_no_historico_zera_fase_stage_mas_preserva_fase_nome(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=108)
        destino = PipelineStage.objects.create(nome='ParaApagar', ordem=109)
        destino_final = PipelineStage.objects.create(nome='Final', ordem=110)
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)
        perfil.avancar_fase(destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()

        destino.excluir_e_realocar(destino=destino_final)
        entrada.refresh_from_db()

        self.assertEqual(entrada.fase_nome, 'ParaApagar')
        self.assertIsNone(entrada.fase_stage)

    def test_profile_creation_signal_records_initial_history_with_fase_stage(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        entrada = perfil.historico_fases.get()
        self.assertEqual(entrada.fase_nome, perfil.fase_atual.nome)
        self.assertEqual(entrada.fase_stage, perfil.fase_atual)


class PipelineStageDeletionTests(TestCase):
    def test_apagar_fase_sem_perfis_nao_exige_destino(self):
        stage = PipelineStage.objects.create(nome='Vazia', ordem=111)
        stage.excluir_e_realocar()
        self.assertFalse(PipelineStage.objects.filter(pk=stage.pk).exists())

    def test_apagar_fase_com_perfis_sem_destino_levanta_erro(self):
        stage = PipelineStage.objects.create(nome='ComPerfil', ordem=112)
        Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=stage)
        with self.assertRaises(ValueError):
            stage.excluir_e_realocar()

    def test_apagar_fase_com_perfis_move_para_destino_escolhido(self):
        origem = PipelineStage.objects.create(nome='ComPerfil2', ordem=113)
        destino = PipelineStage.objects.create(nome='NovoDestino', ordem=114)
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)

        origem.excluir_e_realocar(destino=destino)
        perfil.refresh_from_db()

        self.assertEqual(perfil.fase_atual, destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()
        self.assertIn('removida do pipeline', entrada.observacao)

    def test_apagar_ultima_fase_restante_levanta_erro(self):
        PipelineStage.objects.exclude(pk=PipelineStage.objects.order_by('ordem').first().pk).delete()
        ultima = PipelineStage.objects.get()
        with self.assertRaises(ValueError):
            ultima.excluir_e_realocar()

    def test_apagar_fase_remove_rotas_que_a_referenciam(self):
        a = PipelineStage.objects.create(nome='A', ordem=120)
        b = PipelineStage.objects.create(nome='B', ordem=121)
        c = PipelineStage.objects.create(nome='C', ordem=122)
        PipelineRoute.objects.create(origem=a, destino=b, rotulo='Padrão')
        PipelineRoute.objects.create(origem=b, destino=c, rotulo='Padrão')

        b.excluir_e_realocar(destino=c)

        self.assertEqual(PipelineRoute.objects.count(), 0)
```

Also update the two import lines at the top of `profiles/tests.py`:

```python
from .models import PhaseHistory, PipelineStage, Profile
```

becomes:

```python
from .models import PhaseHistory, PipelineRoute, PipelineStage, Profile
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test profiles.tests.PipelineStageModelTests profiles.tests.PipelineStageDeletionTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'PipelineRoute'`.

- [ ] **Step 3: Rewrite the relevant parts of `profiles/models.py`**

Add `posicao_x`/`posicao_y` to `PipelineStage`, remove `reordenar`, rewrite `excluir_e_realocar`:

```python
class PipelineStage(models.Model):
    """Uma fase do pipeline, editável via UI (tela 'Configurar pipeline')."""

    nome = models.CharField('Nome da fase', max_length=150)
    ordem = models.PositiveIntegerField('Ordem', unique=True)
    posicao_x = models.IntegerField('Posição X no canvas', default=0)
    posicao_y = models.IntegerField('Posição Y no canvas', default=0)

    class Meta:
        ordering = ['ordem']
        verbose_name = 'Fase do pipeline'
        verbose_name_plural = 'Fases do pipeline'

    def __str__(self):
        return self.nome

    def excluir_e_realocar(self, destino=None, usuario=None):
        """Apaga a fase. Se houver perfis nela, `destino` é obrigatório e recebe os
        perfis afetados (com auditoria). Levanta ValueError se for a última fase
        restante do pipeline, ou se houver perfis mas nenhum destino foi informado."""
        if PipelineStage.objects.count() <= 1:
            raise ValueError('Não é possível apagar a última fase restante do pipeline.')

        afetados = list(Profile.objects.filter(fase_atual=self))
        if afetados and destino is None:
            raise ValueError('Escolha uma fase de destino para os perfis desta fase.')

        with transaction.atomic():
            for perfil in afetados:
                perfil.fase_atual = destino
                perfil.save(update_fields=['fase_atual', 'atualizado_em'])
                PhaseHistory.objects.create(
                    perfil=perfil,
                    fase_nome=destino.nome,
                    fase_stage=destino,
                    usuario=usuario,
                    observacao='Movido automaticamente: a fase anterior foi removida do pipeline.',
                )
            self.delete()
```

Add the new `PipelineRoute` model right after `PipelineStage`:

```python
class PipelineRoute(models.Model):
    """Uma rota possível entre duas fases do pipeline (aresta do grafo)."""

    origem = models.ForeignKey(
        PipelineStage,
        verbose_name='Fase de origem',
        on_delete=models.CASCADE,
        related_name='rotas_saida',
    )
    destino = models.ForeignKey(
        PipelineStage,
        verbose_name='Fase de destino',
        on_delete=models.CASCADE,
        related_name='rotas_entrada',
    )
    rotulo = models.CharField('Rótulo', max_length=100)

    class Meta:
        unique_together = ('origem', 'destino')
        verbose_name = 'Rota do pipeline'
        verbose_name_plural = 'Rotas do pipeline'

    def __str__(self):
        return f'{self.origem.nome} → {self.destino.nome} ({self.rotulo})'
```

In `Profile`, replace `fase_index`/`fases_concluidas`/`fase_progress_percent`/`proxima_fase`/
`is_concluido`/`avancar_fase` entirely with:

```python
    @property
    def rotas_disponiveis(self):
        return self.fase_atual.rotas_saida.select_related('destino')

    @property
    def is_concluido(self):
        return not self.fase_atual.rotas_saida.exists()

    def avancar_fase(self, destino, usuario=None, observacao=''):
        """Avança o perfil para `destino`, se for uma rota válida a partir da fase
        atual. Retorna True se avançou, False se `destino` não é uma rota configurada."""
        valido = self.fase_atual.rotas_saida.filter(destino=destino).exists()
        if not valido:
            return False
        self.fase_atual = destino
        self.save(update_fields=['fase_atual', 'atualizado_em'])
        PhaseHistory.objects.create(
            perfil=self,
            fase_nome=destino.nome,
            fase_stage=destino,
            usuario=usuario,
            observacao=observacao,
        )
        return True
```

In `PhaseHistory`, add `fase_stage` right after `fase_nome`:

```python
    fase_stage = models.ForeignKey(
        'PipelineStage',
        verbose_name='Fase (referência)',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
```

- [ ] **Step 4: Write the migration**

`profiles/migrations/0005_pipelineroute_and_fase_stage.py`:

```python
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0004_pipelinestage_cutover'),
    ]

    operations = [
        migrations.AddField(
            model_name='pipelinestage',
            name='posicao_x',
            field=models.IntegerField(default=0, verbose_name='Posição X no canvas'),
        ),
        migrations.AddField(
            model_name='pipelinestage',
            name='posicao_y',
            field=models.IntegerField(default=0, verbose_name='Posição Y no canvas'),
        ),
        migrations.AddField(
            model_name='phasehistory',
            name='fase_stage',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='profiles.pipelinestage',
                verbose_name='Fase (referência)',
            ),
        ),
        migrations.CreateModel(
            name='PipelineRoute',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rotulo', models.CharField(max_length=100, verbose_name='Rótulo')),
                ('destino', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rotas_entrada', to='profiles.pipelinestage', verbose_name='Fase de destino')),
                ('origem', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rotas_saida', to='profiles.pipelinestage', verbose_name='Fase de origem')),
            ],
            options={
                'verbose_name': 'Rota do pipeline',
                'verbose_name_plural': 'Rotas do pipeline',
                'unique_together': {('origem', 'destino')},
            },
        ),
    ]
```

- [ ] **Step 5: Data migration — connect the 7 existing stages linearly**

The 7 stages seeded by migration `0003` currently have no routes between them (routes didn't
exist yet), so after `0005` every stage would look terminal. Add
`profiles/migrations/0006_seed_linear_routes.py` to give the existing pipeline a sane starting
shape (a straight line 1→2→3→4→5→6→7, `rotulo='Padrão'`), which the canvas editor can then
branch from:

```python
from django.db import migrations


def seed_linear_routes(apps, schema_editor):
    PipelineStage = apps.get_model('profiles', 'PipelineStage')
    PipelineRoute = apps.get_model('profiles', 'PipelineRoute')

    stages = list(PipelineStage.objects.order_by('ordem'))
    for origem, destino in zip(stages, stages[1:]):
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')

    for indice, stage in enumerate(stages):
        stage.posicao_x = indice * 260
        stage.posicao_y = 120
        stage.save(update_fields=['posicao_x', 'posicao_y'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0005_pipelineroute_and_fase_stage'),
    ]

    operations = [
        migrations.RunPython(seed_linear_routes, noop_reverse),
    ]
```

- [ ] **Step 6: Update `profiles/signals.py`**

```python
        PhaseHistory.objects.create(
            perfil=instance,
            fase_nome=instance.fase_atual.nome,
            fase_stage=instance.fase_atual,
            usuario=instance.responsavel,
            observacao='Perfil criado.',
        )
```

- [ ] **Step 7: Update `profiles/admin.py`**

Add `PipelineRoute` to the import and register it; update `PhaseHistoryInline.readonly_fields` to
include the new field:

```python
from .models import (
    BusinessManager,
    PageInfo,
    PhaseHistory,
    PipelineRoute,
    PipelineStage,
    Profile,
    WhatsAppLink,
)
```

```python
    readonly_fields = ('fase_nome', 'fase_stage', 'data_hora', 'usuario', 'observacao')
```

Append after `PipelineStageAdmin`:

```python
@admin.register(PipelineRoute)
class PipelineRouteAdmin(admin.ModelAdmin):
    list_display = ('origem', 'destino', 'rotulo')
    autocomplete_fields = ('origem', 'destino')
```

`PipelineStageAdmin` needs `search_fields = ('nome',)` added for `autocomplete_fields` on
`PipelineRouteAdmin` to work (Django requires the target admin to define `search_fields`):

```python
@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ordem')
    ordering = ('ordem',)
    search_fields = ('nome',)
```

- [ ] **Step 8: Run migrations and tests**

Run: `python manage.py migrate profiles && python manage.py test profiles.tests -v 2`
Expected: existing tests referencing removed properties (`fase_index` etc., the old
`test_avancar_fase_usa_ordem_dinamica`, `test_is_concluido_true_na_ultima_fase`, and everything in
`ProfileViewsPipelineStageTests`/`TemplateRenderingPipelineStageTests`/`PipelineConfigureViewTests`
that calls the old single-arg `avancar_fase()` or renders the now-broken templates) will fail at
this point — that's expected and gets fixed in Tasks 2–3. For this step, only confirm the NEW
tests added in Step 1 pass:

Run: `python manage.py test profiles.tests.PipelineStageModelTests profiles.tests.PipelineStageDeletionTests -v 2`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add profiles/models.py profiles/signals.py profiles/admin.py profiles/migrations/0005_pipelineroute_and_fase_stage.py profiles/migrations/0006_seed_linear_routes.py profiles/tests.py
git commit -m "feat: add PipelineRoute model and fase_stage for branching pipeline"
```

---

## Task 2: Advance-phase flow for multiple routes

**Files:**
- Modify: `profiles/views.py`
- Modify: `templates/profiles/_advance_modal.html`
- Delete: `profiles/tests.py` entries that reference the old single-arg flow (superseded, see below)
- Test: `profiles/tests.py`

**Interfaces:**
- Consumes: `Profile.rotas_disponiveis`, `Profile.avancar_fase(destino, ...)` from Task 1.
- Produces: `profile_advance_phase` now requires `destino` (stage pk) in POST when the current
  stage has more than one route; with exactly one route it still works with no `destino` supplied
  (auto-picks the only option, preserving today's one-click UX).

- [ ] **Step 1: Replace the obsolete tests in `ProfileViewsPipelineStageTests`**

`test_avancar_fase_view_usa_nome_da_fase` currently POSTs with no body and relies on `ordem`-based
auto-advance. Replace it with:

```python
    def test_avancar_fase_view_com_uma_rota_nao_exige_destino(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        destino = perfil.fase_atual.rotas_saida.get().destino
        resp = self.client.post(reverse('profiles:profile_advance_phase', args=[perfil.pk]), follow=True)
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, destino)

    def test_avancar_fase_view_com_multiplas_rotas_exige_destino(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        origem = perfil.fase_atual
        alternativa = PipelineStage.objects.create(nome='Alternativa', ordem=200)
        PipelineRoute.objects.create(origem=origem, destino=alternativa, rotulo='Falhou')

        resp = self.client.post(reverse('profiles:profile_advance_phase', args=[perfil.pk]), follow=True)
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, origem, 'sem destino explícito e mais de uma rota, não deve avançar')

        destino_padrao = origem.rotas_saida.get(rotulo='Padrão').destino
        resp = self.client.post(
            reverse('profiles:profile_advance_phase', args=[perfil.pk]),
            {'destino': alternativa.pk},
            follow=True,
        )
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, alternativa)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test profiles.tests.ProfileViewsPipelineStageTests -v 2`
Expected: FAIL — `profile_advance_phase` still calls the old single-arg `avancar_fase()`.

- [ ] **Step 3: Update `profile_advance_phase` in `profiles/views.py`**

```python
@login_required
@require_POST
def profile_advance_phase(request, pk):
    perfil = get_object_or_404(Profile, pk=pk)
    form = PhaseAdvanceForm(request.POST)
    observacao = form.cleaned_data.get('observacao', '') if form.is_valid() else ''

    destino_pk = request.POST.get('destino')
    if destino_pk:
        destino = get_object_or_404(PipelineStage, pk=destino_pk)
    else:
        rotas = list(perfil.rotas_disponiveis)
        destino = rotas[0].destino if len(rotas) == 1 else None

    if destino and perfil.avancar_fase(destino, usuario=request.user, observacao=observacao):
        messages.success(request, f'Perfil avançado para "{perfil.fase_atual.nome}".')
    else:
        messages.info(request, 'Escolha uma rota válida para avançar este perfil.')

    return redirect('profiles:profile_detail', pk=perfil.pk)
```

- [ ] **Step 4: Update `templates/profiles/_advance_modal.html`**

Replace the body's phase-transition section (the `{% if perfil.proxima_fase %}` block) with one
button per available route:

```html
                    {% with rotas=perfil.rotas_disponiveis %}
                    {% if rotas %}
                        <p class="text-muted small mb-2">Fase atual: <strong>{{ perfil.fase_atual.nome }}</strong></p>
                        <label class="form-label small" for="obs-{{ perfil.pk }}">Observação (opcional)</label>
                        <textarea class="form-control mb-3" id="obs-{{ perfil.pk }}" name="observacao" rows="3"
                            placeholder="Ex: link da página criada, número vinculado, ID do BM..."></textarea>
                        <div class="d-flex flex-column gap-2">
                            {% for rota in rotas %}
                            <button type="submit" name="destino" value="{{ rota.destino.pk }}" class="btn btn-brand text-start">
                                <i class="ph-bold ph-arrow-circle-right"></i> {{ rota.rotulo }} → {{ rota.destino.nome }}
                            </button>
                            {% endfor %}
                        </div>
                    {% else %}
                        <p class="mb-0">Este perfil já está concluído — não há próxima fase.</p>
                    {% endif %}
                    {% endwith %}
```

Remove the old `{% if perfil.proxima_fase %}<button type="submit" class="btn btn-brand">...`
footer button entirely (each route is now its own submit button inside `.modal-body`, so
`.modal-footer` keeps only "Cancelar").

- [ ] **Step 5: Run tests, verify green**

Run: `python manage.py test profiles.tests.ProfileViewsPipelineStageTests -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add profiles/views.py templates/profiles/_advance_modal.html profiles/tests.py
git commit -m "feat: support choosing among multiple routes when advancing a profile"
```

---

## Task 3: JSON-ify stage views, add move/route endpoints, remove reorder

**Files:**
- Modify: `profiles/views.py`
- Modify: `profiles/urls.py`
- Modify: `profiles/forms.py`
- Test: `profiles/tests.py`

**Interfaces:**
- Consumes: `PipelineRoute`, `PipelineStage.posicao_x/y` from Task 1.
- Produces: `pipeline_stage_create/rename/delete` now return `JsonResponse` instead of
  redirect+Django-messages. New: `pipeline_stage_move`, `pipeline_route_create`,
  `pipeline_route_delete`, `pipeline_graph_data` (GET, returns the full stage+route graph as
  JSON for the canvas to import), `profile_traversal_data` (GET, returns one profile's visited
  stages/routes for the read-only map). Removed: `pipeline_stage_reorder` and its URL.

- [ ] **Step 1: Write failing tests**

Replace `PipelineConfigureViewTests` (its `test_reordenar_via_post_persiste_nova_ordem` and the
redirect-based assertions no longer apply) with:

```python
class PipelineConfigureApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa3', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa3', password='senha-forte-123')

    def test_pipeline_graph_data_retorna_fases_e_rotas(self):
        resp = self.client.get(reverse('profiles:pipeline_graph_data'))
        data = resp.json()
        self.assertEqual(len(data['stages']), 7)
        self.assertEqual(len(data['routes']), 6)
        self.assertIn('rotulo', data['routes'][0])

    def test_criar_fase_via_json(self):
        resp = self.client.post(reverse('profiles:pipeline_stage_create'), {'nome': 'Nova'})
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(PipelineStage.objects.get(pk=data['stage']['id']).nome, 'Nova')

    def test_criar_fase_sem_nome_retorna_erro_json(self):
        resp = self.client.post(reverse('profiles:pipeline_stage_create'), {'nome': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_renomear_fase_via_json(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        resp = self.client.post(reverse('profiles:pipeline_stage_rename', args=[stage.pk]), {'nome': 'Mudou'})
        self.assertTrue(resp.json()['ok'])
        stage.refresh_from_db()
        self.assertEqual(stage.nome, 'Mudou')

    def test_mover_fase_persiste_posicao(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        resp = self.client.post(
            reverse('profiles:pipeline_stage_move', args=[stage.pk]),
            {'x': 340, 'y': 210},
        )
        self.assertTrue(resp.json()['ok'])
        stage.refresh_from_db()
        self.assertEqual((stage.posicao_x, stage.posicao_y), (340, 210))

    def test_apagar_fase_sem_perfis_via_json(self):
        stage = PipelineStage.objects.create(nome='Solta', ordem=200)
        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[stage.pk]))
        self.assertTrue(resp.json()['ok'])
        self.assertFalse(PipelineStage.objects.filter(pk=stage.pk).exists())

    def test_apagar_fase_com_perfis_sem_destino_retorna_erro_precisa_destino(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=stage)
        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[stage.pk]))
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['reason'], 'precisa_destino')

    def test_apagar_fase_com_perfis_e_destino_via_json(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        origem, destino = stages[0], stages[1]
        Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)
        resp = self.client.post(
            reverse('profiles:pipeline_stage_delete', args=[origem.pk]),
            {'destino': destino.pk},
        )
        self.assertTrue(resp.json()['ok'])

    def test_criar_rota_via_json(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        a, c = stages[0], stages[2]
        resp = self.client.post(reverse('profiles:pipeline_route_create'), {
            'origem': a.pk, 'destino': c.pk, 'rotulo': 'Atalho',
        })
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(PipelineRoute.objects.filter(origem=a, destino=c, rotulo='Atalho').exists())

    def test_apagar_rota_via_json(self):
        rota = PipelineRoute.objects.first()
        resp = self.client.post(reverse('profiles:pipeline_route_delete', args=[rota.pk]))
        self.assertTrue(resp.json()['ok'])
        self.assertFalse(PipelineRoute.objects.filter(pk=rota.pk).exists())

    def test_profile_traversal_data_retorna_caminho_percorrido(self):
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x')
        destino = perfil.fase_atual.rotas_saida.get().destino
        perfil.avancar_fase(destino)

        resp = self.client.get(reverse('profiles:profile_traversal_data', args=[perfil.pk]))
        data = resp.json()
        self.assertEqual(len(data['visited_stage_ids']), 2)
        self.assertEqual(data['current_stage_id'], destino.pk)
```

Update the top import in `profiles/tests.py`:

```python
from .models import PhaseHistory, PipelineRoute, PipelineStage, Profile
```

(already done in Task 1 — verify it's still correct, no change needed here.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test profiles.tests.PipelineConfigureApiTests -v 2`
Expected: FAIL — `NoReverseMatch` for `pipeline_graph_data`, `pipeline_stage_move`,
`pipeline_route_create`, `pipeline_route_delete`, `profile_traversal_data` (none exist yet).

- [ ] **Step 3: Update `profiles/views.py`**

Update the import line:

```python
from .models import PipelineStage, Profile, ProfileStatus
```

becomes:

```python
from .models import PipelineRoute, PipelineStage, Profile, ProfileStatus
```

Replace `pipeline_configure`, `pipeline_stage_create`, `pipeline_stage_rename`,
`pipeline_stage_delete`, `pipeline_stage_reorder` (delete this last one entirely) with:

```python
@login_required
def pipeline_configure(request):
    return render(request, 'profiles/pipeline_configure.html')


@login_required
def pipeline_graph_data(request):
    stages = [
        {'id': s.pk, 'nome': s.nome, 'x': s.posicao_x, 'y': s.posicao_y}
        for s in PipelineStage.objects.order_by('ordem')
    ]
    routes = [
        {'id': r.pk, 'origem': r.origem_id, 'destino': r.destino_id, 'rotulo': r.rotulo}
        for r in PipelineRoute.objects.all()
    ]
    return JsonResponse({'stages': stages, 'routes': routes})


@login_required
@require_POST
def pipeline_stage_create(request):
    proxima_ordem = (PipelineStage.objects.aggregate(m=Max('ordem'))['m'] or 0) + 1
    form = PipelineStageForm(request.POST)
    if form.is_valid():
        stage = form.save(commit=False)
        stage.ordem = proxima_ordem
        stage.posicao_x = int(request.POST.get('x', 0))
        stage.posicao_y = int(request.POST.get('y', 0))
        stage.save()
        return JsonResponse({'ok': True, 'stage': {'id': stage.pk, 'nome': stage.nome}})
    return JsonResponse({'ok': False, 'errors': form.errors}, status=400)


@login_required
@require_POST
def pipeline_stage_rename(request, pk):
    stage = get_object_or_404(PipelineStage, pk=pk)
    form = PipelineStageForm(request.POST, instance=stage)
    if form.is_valid():
        form.save()
        return JsonResponse({'ok': True, 'stage': {'id': stage.pk, 'nome': stage.nome}})
    return JsonResponse({'ok': False, 'errors': form.errors}, status=400)


@login_required
@require_POST
def pipeline_stage_move(request, pk):
    stage = get_object_or_404(PipelineStage, pk=pk)
    stage.posicao_x = int(request.POST.get('x', stage.posicao_x))
    stage.posicao_y = int(request.POST.get('y', stage.posicao_y))
    stage.save(update_fields=['posicao_x', 'posicao_y'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def pipeline_stage_delete(request, pk):
    stage = get_object_or_404(PipelineStage, pk=pk)
    destino_pk = request.POST.get('destino')
    destino = get_object_or_404(PipelineStage, pk=destino_pk) if destino_pk else None
    try:
        stage.excluir_e_realocar(destino=destino, usuario=request.user)
        return JsonResponse({'ok': True})
    except ValueError as exc:
        reason = 'precisa_destino' if 'destino' in str(exc) else 'ultima_fase'
        return JsonResponse({'ok': False, 'reason': reason, 'message': str(exc)}, status=400)


@login_required
@require_POST
def pipeline_route_create(request):
    origem = get_object_or_404(PipelineStage, pk=request.POST.get('origem'))
    destino = get_object_or_404(PipelineStage, pk=request.POST.get('destino'))
    rotulo = request.POST.get('rotulo', '').strip() or 'Padrão'
    rota, created = PipelineRoute.objects.get_or_create(
        origem=origem, destino=destino, defaults={'rotulo': rotulo},
    )
    if not created:
        return JsonResponse({'ok': False, 'reason': 'ja_existe'}, status=400)
    return JsonResponse({'ok': True, 'route': {'id': rota.pk, 'rotulo': rota.rotulo}})


@login_required
@require_POST
def pipeline_route_delete(request, pk):
    rota = get_object_or_404(PipelineRoute, pk=pk)
    rota.delete()
    return JsonResponse({'ok': True})


@login_required
def profile_traversal_data(request, pk):
    perfil = get_object_or_404(Profile, pk=pk)
    visited_ids = list(
        perfil.historico_fases.exclude(fase_stage=None)
        .order_by('data_hora')
        .values_list('fase_stage_id', flat=True)
        .distinct()
    )
    return JsonResponse({'visited_stage_ids': visited_ids, 'current_stage_id': perfil.fase_atual_id})
```

- [ ] **Step 4: Update `profiles/urls.py`**

```python
    path('pipeline/', views.pipeline_configure, name='pipeline_configure'),
    path('pipeline/dados/', views.pipeline_graph_data, name='pipeline_graph_data'),
    path('pipeline/criar/', views.pipeline_stage_create, name='pipeline_stage_create'),
    path('pipeline/<int:pk>/renomear/', views.pipeline_stage_rename, name='pipeline_stage_rename'),
    path('pipeline/<int:pk>/mover/', views.pipeline_stage_move, name='pipeline_stage_move'),
    path('pipeline/<int:pk>/apagar/', views.pipeline_stage_delete, name='pipeline_stage_delete'),
    path('pipeline/rotas/criar/', views.pipeline_route_create, name='pipeline_route_create'),
    path('pipeline/rotas/<int:pk>/apagar/', views.pipeline_route_delete, name='pipeline_route_delete'),
    path('perfis/<int:pk>/trajeto/', views.profile_traversal_data, name='profile_traversal_data'),
```

(Replaces the previous five `pipeline/...` lines, dropping `pipeline/reordenar/`; the
`perfis/<int:pk>/trajeto/` line is new and goes alongside the other `perfis/<int:pk>/...` routes.)

- [ ] **Step 5: `profiles/forms.py` — no change needed**

`PipelineStageForm` (from the earlier plan) is reused as-is for both create and rename; confirm it
still only has `fields = ['nome']`.

- [ ] **Step 6: Run tests, verify green**

Run: `python manage.py test profiles.tests -v 2`
Expected: `PipelineConfigureApiTests` passes. Tasks 1–2's tests still pass. The OLD
`PipelineConfigureViewTests` class (redirect-based, from the linear plan) and
`PipelineSidebarLinkTests`/`TemplateRenderingPipelineStageTests` will still be failing at this
point — Task 5 replaces the templates they depend on. Delete the now-superseded
`PipelineConfigureViewTests` class entirely from `profiles/tests.py` in this step (it tests
behavior — redirects, Django messages, `reorder` — that no longer exists by design), since keeping
known-obsolete tests around as permanent red is not the goal; `PipelineConfigureApiTests` above is
its replacement.

- [ ] **Step 7: Commit**

```bash
git add profiles/views.py profiles/urls.py profiles/tests.py
git commit -m "feat: JSON API for pipeline stages/routes, drop reorder endpoint"
```

---

## Task 4: Canvas editor (`pipeline_configure.html`) with Drawflow

**Files:**
- Modify: `templates/profiles/pipeline_configure.html` (full rewrite)
- Modify: `templates/base.html` (swap SortableJS reference for Drawflow; sidebar link unchanged)
- Test: `profiles/tests.py`

**Interfaces:**
- Consumes: `pipeline_graph_data`, `pipeline_stage_create/rename/move/delete`,
  `pipeline_route_create/delete` JSON endpoints from Task 3.
- Produces: nothing consumed elsewhere (self-contained editor page).

- [ ] **Step 1: Get the Drawflow SRI hash**

```bash
curl -s -o /tmp/drawflow.min.js "https://cdn.jsdelivr.net/npm/drawflow@0.0.60/dist/drawflow.min.js" && openssl dgst -sha384 -binary /tmp/drawflow.min.js | openssl base64 -A
curl -s -o /tmp/drawflow.min.css "https://cdn.jsdelivr.net/npm/drawflow@0.0.60/dist/drawflow.min.css" && openssl dgst -sha384 -binary /tmp/drawflow.min.css | openssl base64 -A
```

Use the two resulting hashes in Step 3 below (do not fabricate them — compute from the actual
downloaded files, same process used for the SortableJS `<script>` tag earlier this session).

- [ ] **Step 2: Write a smoke test**

```python
class PipelineCanvasTemplateTests(TestCase):
    def test_pipeline_configure_carrega_drawflow(self):
        user = User.objects.create_user(username='qa5', password='senha-forte-123')
        client = Client()
        client.login(username='qa5', password='senha-forte-123')
        resp = client.get(reverse('profiles:pipeline_configure'))
        self.assertContains(resp, 'drawflow')
        self.assertContains(resp, reverse('profiles:pipeline_graph_data'))
```

Run: `python manage.py test profiles.tests.PipelineCanvasTemplateTests -v 2` → expect FAIL (old
template has neither).

- [ ] **Step 3: Rewrite `templates/profiles/pipeline_configure.html`**

```html
{% extends 'base.html' %}
{% block title %}Configurar pipeline{% endblock %}
{% block extra_head %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/drawflow@0.0.60/dist/drawflow.min.css" integrity="sha384-<CSS_HASH_FROM_STEP_1>" crossorigin="anonymous">
<style>
    #pipelineCanvas { width: 100%; height: calc(100vh - 220px); background: var(--bg-page); border: 1px solid var(--border-subtle); border-radius: .75rem; }
    .pipeline-node { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: .6rem; padding: .6rem .8rem; min-width: 10rem; box-shadow: var(--shadow-card); }
    .pipeline-node__name { background: transparent; border: none; font-family: var(--font-body); font-weight: 500; color: var(--text-body); width: 100%; }
    .pipeline-node__name:focus { outline: none; border-bottom: 1px solid var(--accent-on-surface); }
    .pipeline-node__delete { background: none; border: none; color: var(--text-muted); padding: 0; margin-left: .4rem; }
    .pipeline-node__delete:hover { color: var(--status-danger); }
    .drawflow .drawflow-node { padding: 0; }
    .drawflow .connection .main-path { stroke: var(--text-muted); stroke-width: 2px; }
    .drawflow .connection .main-path:hover { stroke: var(--signal-amber); }
</style>
{% endblock %}
{% block content %}
<div class="page-header">
    <div>
        <p class="page-header__eyebrow">Pipeline</p>
        <h1 class="page-header__title">Configurar pipeline</h1>
    </div>
    <button type="button" class="btn btn-brand" id="addStageBtn"><i class="ph-bold ph-plus"></i> Nova fase</button>
</div>
<p class="text-muted small">Arraste uma fase pra mover. Puxe uma linha da borda de uma fase até outra pra criar uma rota. Clique duplo no nome pra renomear.</p>
<div id="pipelineCanvas" data-graph-url="{% url 'profiles:pipeline_graph_data' %}"></div>
{% endblock %}
{% block extra_js %}
<script src="https://cdn.jsdelivr.net/npm/drawflow@0.0.60/dist/drawflow.min.js" integrity="sha384-<JS_HASH_FROM_STEP_1>" crossorigin="anonymous"></script>
<script>
document.addEventListener('DOMContentLoaded', function () {
    var container = document.getElementById('pipelineCanvas');
    var editor = new Drawflow(container);
    editor.reroute = true;
    editor.start();

    function csrfToken() {
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

    function post(url, params) {
        var body = new URLSearchParams(params);
        return fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken() }, body: body })
            .then(function (r) { return r.json().then(function (data) { return { status: r.status, data: data }; }); });
    }

    function nodeHtml(nome) {
        return '<div class="pipeline-node">' +
            '<input class="pipeline-node__name" value="' + nome.replace(/"/g, '&quot;') + '" readonly>' +
            '<button type="button" class="pipeline-node__delete" title="Apagar"><i class="ph-bold ph-trash"></i></button>' +
            '</div>';
    }

    function wireNode(nodeId, stageId) {
        var el = document.getElementById('node-' + nodeId);
        var input = el.querySelector('.pipeline-node__name');
        var delBtn = el.querySelector('.pipeline-node__delete');

        input.addEventListener('dblclick', function () { input.readOnly = false; input.focus(); });
        input.addEventListener('blur', function () {
            input.readOnly = true;
            post("{% url 'profiles:pipeline_stage_rename' 0 %}".replace('0', stageId), { nome: input.value });
        });

        delBtn.addEventListener('click', function () {
            post("{% url 'profiles:pipeline_stage_delete' 0 %}".replace('0', stageId), {}).then(function (res) {
                if (res.data.ok) { editor.removeNodeId('node-' + nodeId); return; }
                if (res.data.reason === 'precisa_destino') {
                    var destinoId = prompt('Esta fase tem perfis. Informe o ID da fase de destino (veja os IDs no admin) para mover os perfis antes de apagar:');
                    if (destinoId) {
                        post("{% url 'profiles:pipeline_stage_delete' 0 %}".replace('0', stageId), { destino: destinoId }).then(function (res2) {
                            if (res2.data.ok) editor.removeNodeId('node-' + nodeId);
                            else alert(res2.data.message || 'Não foi possível apagar.');
                        });
                    }
                } else {
                    alert(res.data.message || 'Não foi possível apagar.');
                }
            });
        });
    }

    var stageIdByNodeId = {};

    fetch(container.dataset.graphUrl).then(function (r) { return r.json(); }).then(function (graph) {
        graph.stages.forEach(function (stage) {
            var nodeId = editor.addNode(
                'stage', 1, 1, stage.x, stage.y, 'stage-' + stage.id, {}, nodeHtml(stage.nome),
            );
            stageIdByNodeId[nodeId] = stage.id;
            wireNode(nodeId, stage.id);
        });

        graph.routes.forEach(function (route) {
            var origemNodeId = Object.keys(stageIdByNodeId).find(function (k) { return stageIdByNodeId[k] === route.origem; });
            var destinoNodeId = Object.keys(stageIdByNodeId).find(function (k) { return stageIdByNodeId[k] === route.destino; });
            if (origemNodeId && destinoNodeId) {
                editor.addConnection(origemNodeId, destinoNodeId, 'output_1', 'input_1');
            }
        });
    });

    editor.on('nodeMoved', function (nodeId) {
        var pos = editor.drawflow.drawflow.Home.data[nodeId].pos;
        post("{% url 'profiles:pipeline_stage_move' 0 %}".replace('0', stageIdByNodeId[nodeId]), { x: Math.round(pos[0]), y: Math.round(pos[1]) });
    });

    editor.on('connectionCreated', function (info) {
        var rotulo = prompt('Rótulo desta rota (ex: Padrão, Falhou):', 'Padrão');
        if (rotulo === null) { editor.removeSingleConnection(info.output_id, info.input_id, info.output_class, info.input_class); return; }
        post("{% url 'profiles:pipeline_route_create' %}", {
            origem: stageIdByNodeId[info.output_id], destino: stageIdByNodeId[info.input_id], rotulo: rotulo,
        });
    });

    document.getElementById('addStageBtn').addEventListener('click', function () {
        var nome = prompt('Nome da nova fase:');
        if (!nome) return;
        post("{% url 'profiles:pipeline_stage_create' %}", { nome: nome, x: 100, y: 100 }).then(function (res) {
            if (res.data.ok) {
                var nodeId = editor.addNode('stage', 1, 1, 100, 100, 'stage-' + res.data.stage.id, {}, nodeHtml(res.data.stage.nome));
                stageIdByNodeId[nodeId] = res.data.stage.id;
                wireNode(nodeId, res.data.stage.id);
            }
        });
    });
});
</script>
{% endblock %}
```

- [ ] **Step 4: Update `templates/base.html` — drop SortableJS**

The linear list editor (removed by this plan) was the only consumer of SortableJS. Search
`templates/base.html`'s block-`extra_js` inclusion pattern is per-template
(`pipeline_configure.html` loaded its own `<script>` tag — it wasn't in `base.html` itself), so
this step is actually a no-op for `base.html`: the SortableJS `<script>` tag lived only in the old
`pipeline_configure.html`, which Step 3 already replaced. Verify with:

```bash
grep -rn "sortablejs" templates/
```

Expected: no matches after Step 3 (confirm rather than edit — if this greps clean, there is
nothing further to do in this step).

- [ ] **Step 5: Run tests, verify green**

Run: `python manage.py test profiles.tests.PipelineCanvasTemplateTests -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/profiles/pipeline_configure.html profiles/tests.py
git commit -m "feat: replace drag-and-drop pipeline list with Drawflow canvas editor"
```

---

## Task 5: Read-only map — profile detail page + "ver mapa" modal on the list

**Files:**
- Delete: `templates/profiles/_pipeline_track.html`
- Create: `templates/profiles/_pipeline_map.html` (shared partial, both contexts include it)
- Modify: `templates/profiles/profile_detail.html`
- Modify: `templates/profiles/profile_list.html`
- Modify: `templates/base.html` (remove now-dead `.pipeline-track*` CSS, no new CSS needed —
  `.pipeline-node`/canvas styles are already in `pipeline_configure.html`'s own `extra_head` block
  from Task 4; the read-only map reuses those same classes, so this partial needs its own
  `{% block extra_head %}`-equivalent... see Step 1 note below on why this lives inline instead)
- Test: `profiles/tests.py`

**Interfaces:**
- Consumes: `pipeline_graph_data`, `profile_traversal_data` (Task 3), Drawflow CDN tag pattern
  (Task 4).
- Produces: nothing consumed elsewhere (leaf UI feature).

- [ ] **Step 1: Write failing tests**

```python
class PipelineMapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa6', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa6', password='senha-forte-123')

    def test_profile_detail_inclui_canvas_de_mapa(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'pipelineMap')
        self.assertContains(resp, reverse('profiles:profile_traversal_data', args=[perfil.pk]))

    def test_profile_list_tem_botao_ver_mapa(self):
        Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_list'))
        self.assertContains(resp, 'Ver mapa')
```

Run: `python manage.py test profiles.tests.PipelineMapTests -v 2` → expect FAIL.

- [ ] **Step 2: Create `templates/profiles/_pipeline_map.html`**

A self-contained partial: takes `canvas_id` (unique DOM id, since the list page's modal and the
detail page both need one) and `traversal_url` (or none, for the pure-editor case — not used
here, always provided in this context). Loads its own Drawflow `<link>`/`<script>` tags guarded
so they're only injected once even if the partial is used twice on the same page (it isn't, in
this plan, but guard anyway since the list page's modal is dynamically populated):

```html
{% comment %}
Uso: {% include 'profiles/_pipeline_map.html' with canvas_id='pipelineMap' traversal_url=... %}
Canvas Drawflow somente-leitura, com o caminho percorrido pelo perfil destacado.
{% endcomment %}
<div id="{{ canvas_id }}" class="pipeline-map" data-graph-url="{% url 'profiles:pipeline_graph_data' %}" data-traversal-url="{{ traversal_url }}"></div>
<script>
(function () {
    function loadDrawflowOnce(callback) {
        if (window.Drawflow) { callback(); return; }
        if (window._drawflowLoading) { window._drawflowLoading.then(callback); return; }
        var css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = 'https://cdn.jsdelivr.net/npm/drawflow@0.0.60/dist/drawflow.min.css';
        css.integrity = 'sha384-<CSS_HASH_FROM_TASK_4_STEP_1>';
        css.crossOrigin = 'anonymous';
        document.head.appendChild(css);
        window._drawflowLoading = new Promise(function (resolve) {
            var script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/drawflow@0.0.60/dist/drawflow.min.js';
            script.integrity = 'sha384-<JS_HASH_FROM_TASK_4_STEP_1>';
            script.crossOrigin = 'anonymous';
            script.onload = resolve;
            document.head.appendChild(script);
        });
        window._drawflowLoading.then(callback);
    }

    function renderMap(containerId) {
        var container = document.getElementById(containerId);
        if (!container || container.dataset.rendered) return;
        container.dataset.rendered = '1';
        var editor = new Drawflow(container);
        editor.editor_mode = 'view';
        editor.start();

        Promise.all([
            fetch(container.dataset.graphUrl).then(function (r) { return r.json(); }),
            fetch(container.dataset.traversalUrl).then(function (r) { return r.json(); }),
        ]).then(function (results) {
            var graph = results[0], traversal = results[1];
            var stageIdByNodeId = {};
            graph.stages.forEach(function (stage) {
                var visited = traversal.visited_stage_ids.indexOf(stage.id) !== -1;
                var current = traversal.current_stage_id === stage.id;
                var cls = current ? 'pipeline-node pipeline-node--current' : (visited ? 'pipeline-node pipeline-node--visited' : 'pipeline-node');
                var nodeId = editor.addNode('stage', 0, 0, stage.x, stage.y, 'stage-' + stage.id, {}, '<div class="' + cls + '"><span class="pipeline-node__name">' + stage.nome + '</span></div>');
                stageIdByNodeId[nodeId] = stage.id;
            });
            graph.routes.forEach(function (route) {
                var o = Object.keys(stageIdByNodeId).find(function (k) { return stageIdByNodeId[k] === route.origem; });
                var d = Object.keys(stageIdByNodeId).find(function (k) { return stageIdByNodeId[k] === route.destino; });
                if (o && d) editor.addConnection(o, d, 'output_1', 'input_1');
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        loadDrawflowOnce(function () { renderMap('{{ canvas_id }}'); });
    });
})();
</script>
```

- [ ] **Step 3: Add read-only node styling to `templates/base.html`**

Remove the entire `/* Pipeline track — signature element */` through
`/* Mini pipeline track — dense list rows */` CSS block (both `.pipeline-track*` rule sets — they
have no more markup consumers after Step 5 of this task). Add in its place:

```css
        /* Pipeline map (read-only canvas) — profile detail + list modal */
        .pipeline-map { width: 100%; height: 22rem; background: var(--bg-page); border: 1px solid var(--border-subtle); border-radius: .75rem; }
        .pipeline-map .drawflow-node { padding: 0; }
        .pipeline-node { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: .6rem; padding: .5rem .75rem; font-size: .85rem; color: var(--text-muted); }
        .pipeline-node--visited { border-color: var(--status-success); color: var(--text-body); }
        .pipeline-node--current { border-color: var(--signal-amber); color: var(--text-body); font-weight: 600; box-shadow: 0 0 0 3px rgba(221,139,46,.2); }
```

- [ ] **Step 4: Update `templates/profiles/profile_detail.html`**

Replace `{% include 'profiles/_pipeline_track.html' with perfil=perfil size='full' %}` with:

```html
        {% include 'profiles/_pipeline_map.html' with canvas_id='pipelineMap' traversal_url=perfil.get_absolute_url|add:'trajeto/' %}
```

Since `get_absolute_url` doesn't include `trajeto/`, use the named URL directly instead — replace
the line above with:

```html
        {% include 'profiles/_pipeline_map.html' with canvas_id='pipelineMap' traversal_url=traversal_url %}
```

and add `traversal_url` to the view context in `profiles/views.py`'s `profile_detail`:

```python
    return render(request, 'profiles/profile_detail.html', {
        'perfil': perfil,
        'historico': perfil.historico_fases.all(),
        'paginas': perfil.paginas.all(),
        'whatsapp_links': perfil.whatsapp_links.all(),
        'business_manager': business_manager,
        'traversal_url': reverse('profiles:profile_traversal_data', args=[perfil.pk]),
    })
```

(add `from django.urls import reverse` to `profiles/views.py`'s imports if not already present —
it is not currently imported there, only used via `Profile.get_absolute_url` in `models.py`.)

Also remove the now-dead `{% if not perfil.proxima_fase %}` conditional success banner right below
it (`perfil.proxima_fase` no longer exists) — replace with `{% if perfil.is_concluido %}`:

```html
        {% if perfil.is_concluido %}
        <div class="alert alert-success mt-3 mb-0"><i class="ph-bold ph-check-circle"></i> Perfil concluído — todas as fases finalizadas.</div>
        {% endif %}
```

And the two other `perfil.proxima_fase` references in this file (the "Avançar fase" button's
`disabled` guard) become `perfil.is_concluido`:

```html
        <button type="button" class="btn btn-brand" data-bs-toggle="modal" data-bs-target="#advanceModal{{ perfil.pk }}" {% if perfil.is_concluido %}disabled{% endif %}>
```

- [ ] **Step 5: Update `templates/profiles/profile_list.html`**

Replace the mini-track cell:

```html
                    <td>
                        {% include 'profiles/_pipeline_track.html' with perfil=perfil size='mini' %}
                        <div class="text-muted small mt-1">{{ perfil.fase_atual.nome }}</div>
                    </td>
```

with:

```html
                    <td>
                        <div class="text-muted small mb-1">{{ perfil.fase_atual.nome }}</div>
                        <button type="button" class="btn btn-sm btn-outline-ink" data-bs-toggle="modal" data-bs-target="#mapModal" data-traversal-url="{% url 'profiles:profile_traversal_data' perfil.pk %}">
                            <i class="ph-bold ph-flow-arrow"></i> Ver mapa
                        </button>
                    </td>
```

and the `{% if not perfil.proxima_fase %}disabled{% endif %}` guard on the "Avançar" button in
this same file becomes `{% if perfil.is_concluido %}disabled{% endif %}`.

Add a single shared modal near the bottom of the file, right before the closing
`{% for perfil in perfis %}...{% include 'profiles/_advance_modal.html' ... %}{% endfor %}` block:

```html
<div class="modal fade" id="mapModal" tabindex="-1" aria-labelledby="mapModalLabel" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered modal-lg">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title" id="mapModalLabel">
                    <span class="modal-icon-badge"><i class="ph-bold ph-flow-arrow"></i></span>
                    Mapa do pipeline
                </h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fechar"></button>
            </div>
            <div class="modal-body" id="mapModalBody"></div>
        </div>
    </div>
</div>
<script>
document.getElementById('mapModal').addEventListener('show.bs.modal', function (event) {
    var url = event.relatedTarget.dataset.traversalUrl;
    var body = document.getElementById('mapModalBody');
    body.innerHTML = '';
    var wrapper = document.createElement('div');
    wrapper.id = 'mapModalCanvas';
    wrapper.className = 'pipeline-map';
    wrapper.dataset.graphUrl = "{% url 'profiles:pipeline_graph_data' %}";
    wrapper.dataset.traversalUrl = url;
    body.appendChild(wrapper);
    if (window.renderPipelineMapInto) { window.renderPipelineMapInto('mapModalCanvas'); }
});
</script>
```

This requires `_pipeline_map.html`'s inline script (Task 5 Step 2) to expose its render function
globally instead of only auto-running on `DOMContentLoaded` — go back and adjust
`templates/profiles/_pipeline_map.html`: wrap the `loadDrawflowOnce`/`renderMap` pair so
`renderMap` is also assigned to `window.renderPipelineMapInto = renderMap;` right after its
definition, and keep the existing `DOMContentLoaded` auto-render for the profile-detail usage (it
still needs to render itself immediately on page load there, since it's not inside a modal).

- [ ] **Step 6: Delete `templates/profiles/_pipeline_track.html`**

```bash
git rm templates/profiles/_pipeline_track.html
```

- [ ] **Step 7: Run full test suite**

Run: `python manage.py test profiles.tests -v 2`
Expected: PASS — every test across all 5 tasks in this plan, plus everything still valid from the
earlier linear-pipeline plan that wasn't superseded (profile CRUD, filter, dashboard counts, etc.).

Run: `python manage.py check`
Expected: no issues.

- [ ] **Step 8: Manual browser verification (required — do not skip)**

Same as the linear plan's precedent: start the dev server, log in as `designreview`, and check by
hand:

```bash
python manage.py runserver
```

1. `/pipeline/` — canvas loads with the 7 seeded stages connected in a line. Add a stage, rename
   one by double-clicking, drag one to a new position and reload to confirm it persisted, draw a
   new connection between two non-adjacent stages and label it, delete that connection.
2. Pick a stage with 2+ outgoing routes (create one via the canvas first if none exist), go to a
   profile currently on that stage, open "Avançar fase" — confirm one button per route appears,
   labeled correctly, and clicking one moves the profile and records the right audit entry.
3. Profile detail page — confirm the read-only map renders, the current stage is highlighted
   amber, previously-visited stages are highlighted green.
4. Profile list — click "Ver mapa" on a row, confirm the modal opens with the correct map for
   that specific profile (open it for two different profiles in a row to confirm the shared modal
   doesn't leak state between them).
5. Try deleting a stage that has profiles on it from the canvas — confirm the destino prompt flow
   works and profiles actually move.
6. Toggle dark mode on each of these screens.

- [ ] **Step 9: Commit**

```bash
git add templates/profiles/_pipeline_map.html templates/profiles/profile_detail.html templates/profiles/profile_list.html templates/base.html profiles/views.py profiles/tests.py
git rm templates/profiles/_pipeline_track.html
git commit -m "feat: read-only pipeline map on profile detail + list, remove old dot-trail"
```

---

## Self-Review Notes

- **Spec coverage:** manual route choice (Task 2), canvas-only editor for stages+routes (Task 4),
  full-map read-only rendering on detail + "ver mapa" modal on the list (Task 5), `fase_stage`
  best-effort pointer alongside immutable `fase_nome` (Task 1), explicit-destino deletion (Task 1
  model method + Task 3 view + Task 4's prompt flow) — every decision from the approved design
  sections has a task.
- **Known follow-up not covered by this plan:** the delete-with-destino UX in Task 4 uses a raw
  `prompt()` asking for a numeric stage ID, which is functional but not polished (no dropdown of
  stage names). Flagged here rather than silently shipped as if it were the final intended UX —
  worth a follow-up pass if it feels too rough after manual QA in Task 5 Step 8.
- **Dead code check:** confirmed `PipelineStage.reordenar`, `pipeline_stage_reorder` view/URL,
  `Profile.fase_index`/`fases_concluidas`/`fase_progress_percent`/`proxima_fase`, and
  `_pipeline_track.html` are all explicitly removed, not left alongside the new system.
