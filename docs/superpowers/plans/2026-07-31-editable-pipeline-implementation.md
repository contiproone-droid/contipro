# Pipeline Editável — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed `Phase(TextChoices)` pipeline (7 hardcoded phases) with an editable `PipelineStage` model, plus a "Configurar pipeline" screen where any logged-in user can create, rename, reorder (drag-and-drop), and delete pipeline stages.

**Architecture:** `PipelineStage` becomes the source of truth for pipeline order (replacing `Phase.ordered_values()`). `Profile.fase_atual` changes from a `CharField(choices=...)` to a `ForeignKey(PipelineStage)`. `PhaseHistory.fase` is renamed to `fase_nome`, a free-text snapshot field (not an FK) so historical audit entries never change meaning when a stage is later renamed or deleted. A 3-stage migration (add temp fields → backfill data → cutover) preserves all existing `Profile`/`PhaseHistory` data during the schema change.

**Tech Stack:** Django 6.0 (existing), no new Python dependencies. Drag-and-drop reordering uses SortableJS loaded from CDN (`cdn.jsdelivr.net`), matching the existing pattern of loading Bootstrap/Chart.js/Phosphor Icons via CDN with no local build step or `static/` directory.

## Global Constraints

- **Single global pipeline.** Not multiple named workflows — every `Profile` follows the same stage sequence.
- **No role-based permissions.** Any logged-in user can edit pipeline structure, same as the rest of the app today (no staff/superuser distinction anywhere).
- **No branching/conditions.** The pipeline stays a linear sequence; only its structure becomes data instead of code.
- **The pipeline can never be empty.** At least 1 stage must always exist — the UI disables the delete button on the last remaining stage, and the model layer raises `ValueError` if deletion is attempted anyway.
- **`PhaseHistory` is an immutable audit snapshot.** It stores the stage's name as plain text *at the moment of the transition*, never a live FK to `PipelineStage` — renaming or deleting a stage must never change what past history entries display.
- **Follow existing codebase conventions**: Django `ModelForm`/`Form` classes for validated user input (see `ProfileForm`, `PhaseAdvanceForm`), raw hand-written `<input>`/`<textarea>` tags matching form field names inside templates rather than `{{ form.field }}` widget rendering (see `_advance_modal.html`), all styling inline in `templates/base.html`'s `<style>` block (no separate CSS files), all JS libraries loaded via CDN in `{% block extra_js %}` (no bundler).

---

## Task 1: `PipelineStage` model + data migration

**Files:**
- Modify: `profiles/models.py` (replace `Phase` class with `PipelineStage` model; update `Profile` and `PhaseHistory`)
- Modify: `profiles/signals.py`
- Create: `profiles/migrations/0002_pipelinestage_add_temp_fields.py`
- Create: `profiles/migrations/0003_seed_pipelinestage_and_backfill.py`
- Create: `profiles/migrations/0004_pipelinestage_cutover.py`
- Test: `profiles/tests.py`

**Interfaces:**
- Produces: `PipelineStage` model with fields `nome` (`CharField`), `ordem` (`PositiveIntegerField`, unique), ordered by `ordem`. `Profile.fase_atual` is now `ForeignKey(PipelineStage, on_delete=PROTECT, related_name='perfis')`. `PhaseHistory.fase_nome` (`CharField`, free text) replaces `PhaseHistory.fase`. `Profile.fase_index`, `.fases_concluidas`, `.fase_progress_percent`, `.proxima_fase`, `.is_concluido`, `.avancar_fase()` keep the same signatures but read from `PipelineStage.objects.order_by('ordem')`. Module-level `fase_inicial_default()` function returns the pk of the first stage by `ordem` (used as `Profile.fase_atual`'s default).
- Consumes: nothing from other tasks (this is the foundation task).

- [ ] **Step 1: Write failing tests against the not-yet-existing model**

Append to `profiles/tests.py` (replacing the placeholder comment):

```python
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import PhaseHistory, PipelineStage, Profile

User = get_user_model()


class PipelineStageModelTests(TestCase):
    def test_migration_seeds_seven_stages_in_order(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        self.assertEqual(len(stages), 7)
        self.assertEqual(stages[0].nome, '1. Perfil criado no AdsPower')
        self.assertEqual(stages[-1].nome, '7. Concluído / Ativo')
        self.assertEqual([s.ordem for s in stages], [1, 2, 3, 4, 5, 6, 7])

    def test_new_profile_defaults_to_first_stage(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        primeira = PipelineStage.objects.order_by('ordem').first()
        self.assertEqual(perfil.fase_atual, primeira)

    def test_avancar_fase_usa_ordem_dinamica(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        segunda = PipelineStage.objects.order_by('ordem')[1]
        avancou = perfil.avancar_fase(observacao='obs')
        perfil.refresh_from_db()
        self.assertTrue(avancou)
        self.assertEqual(perfil.fase_atual, segunda)

    def test_is_concluido_true_na_ultima_fase(self):
        ultima = PipelineStage.objects.order_by('-ordem').first()
        perfil = Profile.objects.create(
            nome='Teste', email='t@example.com', senha='x', fase_atual=ultima,
        )
        self.assertTrue(perfil.is_concluido)
        self.assertIsNone(perfil.proxima_fase)
        self.assertFalse(perfil.avancar_fase())

    def test_renomear_fase_nao_altera_historico_existente(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        perfil.avancar_fase()
        entrada = perfil.historico_fases.order_by('-data_hora').first()
        nome_original = entrada.fase_nome

        segunda = PipelineStage.objects.order_by('ordem')[1]
        segunda.nome = 'Nome renomeado'
        segunda.save(update_fields=['nome'])

        entrada.refresh_from_db()
        self.assertEqual(entrada.fase_nome, nome_original)
        self.assertNotEqual(entrada.fase_nome, 'Nome renomeado')

    def test_profile_creation_signal_records_initial_history_with_fase_nome(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        entrada = perfil.historico_fases.get()
        self.assertEqual(entrada.fase_nome, perfil.fase_atual.nome)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test profiles.tests.PipelineStageModelTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'PipelineStage' from 'profiles.models'`

- [ ] **Step 3: Replace `Phase` with `PipelineStage` in `profiles/models.py`**

Delete the entire `class Phase(models.TextChoices): ...` block (lines 8–29 of the current file) and replace it with:

```python
def fase_inicial_default():
    stage = PipelineStage.objects.order_by('ordem').first()
    return stage.pk if stage else None


class PipelineStage(models.Model):
    """Uma fase do pipeline, editável via UI (tela 'Configurar pipeline')."""

    nome = models.CharField('Nome da fase', max_length=150)
    ordem = models.PositiveIntegerField('Ordem', unique=True)

    class Meta:
        ordering = ['ordem']
        verbose_name = 'Fase do pipeline'
        verbose_name_plural = 'Fases do pipeline'

    def __str__(self):
        return self.nome

    def excluir_e_realocar(self, usuario=None):
        """Apaga a fase, movendo perfis afetados para a fase vizinha e registrando
        auditoria. Levanta ValueError se for a última fase restante do pipeline."""
        todas = list(PipelineStage.objects.order_by('ordem'))
        if len(todas) <= 1:
            raise ValueError('Não é possível apagar a última fase restante do pipeline.')

        idx = todas.index(self)
        destino = todas[1] if idx == 0 else todas[idx - 1]

        with transaction.atomic():
            for perfil in Profile.objects.filter(fase_atual=self):
                perfil.fase_atual = destino
                perfil.save(update_fields=['fase_atual', 'atualizado_em'])
                PhaseHistory.objects.create(
                    perfil=perfil,
                    fase_nome=destino.nome,
                    usuario=usuario,
                    observacao='Movido automaticamente: a fase anterior foi removida do pipeline.',
                )
            self.delete()

    @staticmethod
    def reordenar(pks_em_ordem):
        """Recebe uma lista de PKs de PipelineStage na nova ordem desejada e persiste.
        Usa um deslocamento temporário para não violar a constraint unique de 'ordem'."""
        with transaction.atomic():
            for indice, pk in enumerate(pks_em_ordem):
                PipelineStage.objects.filter(pk=pk).update(ordem=10_000 + indice)
            for indice, pk in enumerate(pks_em_ordem):
                PipelineStage.objects.filter(pk=pk).update(ordem=indice + 1)
```

Add `transaction` to the top-of-file import (change `from django.db import models` to `from django.db import models, transaction`).

Then, inside `class Profile`, change the `fase_atual` field definition from:

```python
    fase_atual = models.CharField(
        'Fase atual',
        max_length=30,
        choices=Phase.choices,
        default=Phase.PERFIL_CRIADO,
    )
```

to:

```python
    fase_atual = models.ForeignKey(
        'PipelineStage',
        verbose_name='Fase atual',
        on_delete=models.PROTECT,
        default=fase_inicial_default,
        related_name='perfis',
    )
```

Then replace the five phase-related properties/methods on `Profile`:

```python
    @property
    def fase_index(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        try:
            return ordem.index(self.fase_atual)
        except ValueError:
            return 0

    @property
    def fases_concluidas(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        return ordem[:self.fase_index]

    @property
    def fase_progress_percent(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        total = len(ordem) - 1
        if total <= 0:
            return 100
        return round(self.fase_index / total * 100)

    @property
    def proxima_fase(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        try:
            idx = ordem.index(self.fase_atual)
        except ValueError:
            return None
        if idx >= len(ordem) - 1:
            return None
        return ordem[idx + 1]

    @property
    def is_concluido(self):
        return self.proxima_fase is None

    def avancar_fase(self, usuario=None, observacao=''):
        """Avança o perfil para a próxima fase e registra no histórico. Retorna True se avançou."""
        proxima = self.proxima_fase
        if proxima is None:
            return False
        self.fase_atual = proxima
        self.save(update_fields=['fase_atual', 'atualizado_em'])
        PhaseHistory.objects.create(
            perfil=self,
            fase_nome=proxima.nome,
            usuario=usuario,
            observacao=observacao,
        )
        return True
```

Finally, in `class PhaseHistory`, change:

```python
    fase = models.CharField('Fase', max_length=30, choices=Phase.choices)
```

to:

```python
    fase_nome = models.CharField('Fase', max_length=150)
```

and update its `__str__`:

```python
    def __str__(self):
        return f'{self.perfil.nome} → {self.fase_nome}'
```

- [ ] **Step 4: Update `profiles/signals.py` to use `fase_nome`**

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PhaseHistory, Profile


@receiver(post_save, sender=Profile)
def registrar_fase_inicial(sender, instance, created, **kwargs):
    """Ao criar um Profile, registra a fase inicial no histórico de auditoria."""
    if created:
        PhaseHistory.objects.create(
            perfil=instance,
            fase_nome=instance.fase_atual.nome,
            usuario=instance.responsavel,
            observacao='Perfil criado.',
        )
```

- [ ] **Step 5: Write the three migrations**

`profiles/migrations/0002_pipelinestage_add_temp_fields.py`:

```python
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PipelineStage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=150, verbose_name='Nome da fase')),
                ('ordem', models.PositiveIntegerField(unique=True, verbose_name='Ordem')),
            ],
            options={
                'verbose_name': 'Fase do pipeline',
                'verbose_name_plural': 'Fases do pipeline',
                'ordering': ['ordem'],
            },
        ),
        migrations.AddField(
            model_name='profile',
            name='fase_atual_stage',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='perfis',
                to='profiles.pipelinestage',
                verbose_name='Fase atual',
            ),
        ),
        migrations.AddField(
            model_name='phasehistory',
            name='fase_nome',
            field=models.CharField(blank=True, default='', max_length=150, verbose_name='Fase'),
        ),
    ]
```

`profiles/migrations/0003_seed_pipelinestage_and_backfill.py`:

```python
from django.db import migrations

FASES_INICIAIS = [
    (1, 'perfil_criado', '1. Perfil criado no AdsPower'),
    (2, 'login_facebook', '2. Login/acesso ao perfil no Facebook'),
    (3, 'verificacao_pagina', '3. Verificação de página do Facebook'),
    (4, 'criacao_pagina', '4. Criação da página'),
    (5, 'vinculo_whatsapp', '5. Vínculo da conta do WhatsApp'),
    (6, 'geracao_bm', '6. Geração do Business Manager'),
    (7, 'concluido', '7. Concluído / Ativo'),
]


def seed_and_backfill(apps, schema_editor):
    PipelineStage = apps.get_model('profiles', 'PipelineStage')
    Profile = apps.get_model('profiles', 'Profile')
    PhaseHistory = apps.get_model('profiles', 'PhaseHistory')

    stage_by_code = {}
    for ordem, codigo, nome in FASES_INICIAIS:
        stage_by_code[codigo] = PipelineStage.objects.create(nome=nome, ordem=ordem)

    for perfil in Profile.objects.all():
        stage = stage_by_code.get(perfil.fase_atual)
        if stage is not None:
            perfil.fase_atual_stage = stage
            perfil.save(update_fields=['fase_atual_stage'])

    for entrada in PhaseHistory.objects.all():
        stage = stage_by_code.get(entrada.fase)
        entrada.fase_nome = stage.nome if stage is not None else entrada.fase
        entrada.save(update_fields=['fase_nome'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0002_pipelinestage_add_temp_fields'),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, noop_reverse),
    ]
```

`profiles/migrations/0004_pipelinestage_cutover.py`:

```python
import django.db.models.deletion
from django.db import migrations, models

import profiles.models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0003_seed_pipelinestage_and_backfill'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='profile',
            name='fase_atual',
        ),
        migrations.RenameField(
            model_name='profile',
            old_name='fase_atual_stage',
            new_name='fase_atual',
        ),
        migrations.AlterField(
            model_name='profile',
            name='fase_atual',
            field=models.ForeignKey(
                default=profiles.models.fase_inicial_default,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='perfis',
                to='profiles.pipelinestage',
                verbose_name='Fase atual',
            ),
        ),
        migrations.RemoveField(
            model_name='phasehistory',
            name='fase',
        ),
        migrations.AlterField(
            model_name='phasehistory',
            name='fase_nome',
            field=models.CharField(max_length=150, verbose_name='Fase'),
        ),
    ]
```

- [ ] **Step 6: Run migrations and tests to verify green**

Run: `python manage.py migrate profiles && python manage.py test profiles.tests.PipelineStageModelTests -v 2`
Expected: PASS (all 6 tests), migration output shows `0002`, `0003`, `0004` applied.

- [ ] **Step 7: Commit**

```bash
git add profiles/models.py profiles/signals.py profiles/migrations/0002_pipelinestage_add_temp_fields.py profiles/migrations/0003_seed_pipelinestage_and_backfill.py profiles/migrations/0004_pipelinestage_cutover.py profiles/tests.py
git commit -m "feat: replace fixed Phase choices with editable PipelineStage model"
```

---

## Task 2: Update views, forms, admin, and context processor

**Files:**
- Modify: `profiles/views.py`
- Modify: `profiles/forms.py`
- Modify: `profiles/context_processors.py`
- Modify: `profiles/admin.py`
- Test: `profiles/tests.py`

**Interfaces:**
- Consumes: `PipelineStage` model, `Profile.fase_atual` (FK), `PhaseHistory.fase_nome` from Task 1.
- Produces: `ProfileFilterForm.fase` as a `ModelChoiceField` over `PipelineStage`; `api_dashboard_data` JSON payload gains an `ordem` key per funnel entry; `fases_ordenadas` context processor returns a `PipelineStage` queryset instead of a list of `Phase` enum members.

- [ ] **Step 1: Write failing tests**

Append to `profiles/tests.py`:

```python
from django.test import Client
from django.urls import reverse


class ProfileViewsPipelineStageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa', password='senha-forte-123')

    def test_filtro_por_fase_na_listagem(self):
        segunda = PipelineStage.objects.order_by('ordem')[1]
        perfil = Profile.objects.create(nome='Alvo', email='a@example.com', senha='x', fase_atual=segunda)
        Profile.objects.create(nome='Outro', email='b@example.com', senha='x')

        resp = self.client.get(reverse('profiles:profile_list'), {'fase': segunda.pk})
        self.assertContains(resp, 'Alvo')
        self.assertNotContains(resp, 'Outro')

    def test_api_dashboard_data_inclui_ordem_por_fase(self):
        resp = self.client.get(reverse('profiles:api_dashboard_data'))
        data = resp.json()
        self.assertEqual(len(data['funil']), 7)
        self.assertEqual(data['funil'][0]['ordem'], 1)
        self.assertEqual(data['funil'][-1]['ordem'], 7)

    def test_dashboard_conta_concluidos_pela_ultima_fase(self):
        ultima = PipelineStage.objects.order_by('-ordem').first()
        Profile.objects.create(nome='Feito', email='f@example.com', senha='x', fase_atual=ultima)
        resp = self.client.get(reverse('profiles:dashboard'))
        self.assertEqual(resp.context['concluidos_total'], 1)

    def test_avancar_fase_view_usa_nome_da_fase(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.post(reverse('profiles:profile_advance_phase', args=[perfil.pk]), follow=True)
        self.assertContains(resp, 'Login/acesso ao perfil no Facebook')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test profiles.tests.ProfileViewsPipelineStageTests -v 2`
Expected: FAIL — `ProfileFilterForm.fase` still a plain `ChoiceField` (filter by pk won't match string choices), `api_dashboard_data` funnel entries missing `ordem` key, dashboard still references the deleted `Phase` name (`ImportError`/`AttributeError`).

- [ ] **Step 3: Update `profiles/forms.py`**

Change the top import and `ProfileFilterForm.fase` field:

```python
from .models import Phase, Profile, ProfileStatus
```

becomes:

```python
from .models import PipelineStage, Profile, ProfileStatus
```

and:

```python
    fase = forms.ChoiceField(
        label='Fase',
        required=False,
        choices=[('', 'Todas as fases')] + list(Phase.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
```

becomes:

```python
    fase = forms.ModelChoiceField(
        label='Fase',
        required=False,
        queryset=PipelineStage.objects.order_by('ordem'),
        empty_label='Todas as fases',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
```

- [ ] **Step 4: Update `profiles/context_processors.py`**

```python
from .models import PipelineStage


def fases_ordenadas(request):
    return {'fases_ordenadas': PipelineStage.objects.order_by('ordem')}
```

- [ ] **Step 5: Update `profiles/views.py`**

Change the top import:

```python
from .models import Phase, Profile, ProfileStatus
```

becomes:

```python
from .models import PipelineStage, Profile, ProfileStatus
```

In `profile_advance_phase`, change:

```python
        messages.success(request, f'Perfil avançado para "{perfil.get_fase_atual_display()}".')
```

to:

```python
        messages.success(request, f'Perfil avançado para "{perfil.fase_atual.nome}".')
```

Replace the `dashboard` view's completion-counting block — change:

```python
    concluidos_mes = Profile.objects.filter(
        fase_atual=Phase.CONCLUIDO,
        atualizado_em__year=agora.year,
        atualizado_em__month=agora.month,
    ).count()
    concluidos_total = Profile.objects.filter(fase_atual=Phase.CONCLUIDO).count()
```

to:

```python
    ultima_fase = PipelineStage.objects.order_by('-ordem').first()
    concluidos_mes = Profile.objects.filter(
        fase_atual=ultima_fase,
        atualizado_em__year=agora.year,
        atualizado_em__month=agora.month,
    ).count() if ultima_fase else 0
    concluidos_total = Profile.objects.filter(fase_atual=ultima_fase).count() if ultima_fase else 0
```

Replace `api_dashboard_data`'s funnel comprehension — change:

```python
    funil = [
        {'fase': label, 'total': Profile.objects.filter(fase_atual=value).count()}
        for value, label in Phase.choices
    ]
```

to:

```python
    funil = [
        {'fase': stage.nome, 'ordem': stage.ordem, 'total': Profile.objects.filter(fase_atual=stage).count()}
        for stage in PipelineStage.objects.order_by('ordem')
    ]
```

- [ ] **Step 6: Update `profiles/admin.py`**

Change the top import:

```python
from .models import (
    BusinessManager,
    PageInfo,
    PhaseHistory,
    Profile,
    WhatsAppLink,
)
```

to:

```python
from .models import (
    BusinessManager,
    PageInfo,
    PhaseHistory,
    PipelineStage,
    Profile,
    WhatsAppLink,
)
```

In `PhaseHistoryInline`, change:

```python
    readonly_fields = ('fase', 'data_hora', 'usuario', 'observacao')
```

to:

```python
    readonly_fields = ('fase_nome', 'data_hora', 'usuario', 'observacao')
```

In `PhaseHistoryAdmin`, change:

```python
    list_display = ('perfil', 'fase', 'data_hora', 'usuario')
    list_filter = ('fase',)
```

to:

```python
    list_display = ('perfil', 'fase_nome', 'data_hora', 'usuario')
    list_filter = ('fase_nome',)
```

Add a registration for `PipelineStage` (append after `BusinessManagerAdmin`):

```python
@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ordem')
    ordering = ('ordem',)
```

- [ ] **Step 7: Run tests to verify green**

Run: `python manage.py test profiles.tests -v 2`
Expected: PASS (all tests from Task 1 and Task 2), plus `python manage.py check` reports no issues.

- [ ] **Step 8: Commit**

```bash
git add profiles/views.py profiles/forms.py profiles/context_processors.py profiles/admin.py profiles/tests.py
git commit -m "feat: wire views/forms/admin to PipelineStage instead of fixed Phase choices"
```

---

## Task 3: Update templates to use `PipelineStage` instead of `Phase`

**Files:**
- Modify: `templates/profiles/_pipeline_track.html`
- Modify: `templates/profiles/_advance_modal.html`
- Modify: `templates/profiles/profile_list.html`
- Modify: `templates/profiles/profile_detail.html`
- Modify: `templates/profiles/profile_form.html`
- Modify: `templates/profiles/dashboard.html`
- Test: `profiles/tests.py`

**Interfaces:**
- Consumes: `fases_ordenadas` context processor (now `PipelineStage` queryset), `Profile.fase_atual` (now an object with `.nome`, not `.get_fase_atual_display()`), `PhaseHistory.fase_nome` (plain attribute, not `.get_fase_display()`), `api_dashboard_data`'s `ordem` key from Task 2.
- Produces: nothing consumed by later tasks (this task is UI-only).

- [ ] **Step 1: Write failing smoke tests**

Append to `profiles/tests.py`:

```python
class TemplateRenderingPipelineStageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa2', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa2', password='senha-forte-123')

    def test_pipeline_track_renderiza_nome_da_fase(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'Perfil criado no AdsPower')

    def test_advance_modal_usa_nome_da_proxima_fase(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'Login/acesso ao perfil no Facebook')

    def test_historico_de_fases_mostra_fase_nome(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'Perfil criado.')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test profiles.tests.TemplateRenderingPipelineStageTests -v 2`
Expected: FAIL with a `TemplateSyntaxError` or `AttributeError`/`FieldError` from templates still calling `get_fase_atual_display`/`.label`/`get_fase_display` against the new FK/plain-text fields (Django templates swallow attribute errors as empty string, so failures will show as missing expected text via `assertContains`).

- [ ] **Step 3: Update `templates/profiles/_pipeline_track.html`**

Change `fase_value.label` (both occurrences) to `fase_value.nome`:

```html
{% load profile_extras %}
{% comment %}
Uso: {% include 'profiles/_pipeline_track.html' with perfil=perfil size='mini' %}
size: 'full' (padrão, com rótulos) ou 'mini' (compacto, sem rótulos, para tabelas)
{% endcomment %}
<div class="pipeline-track pipeline-track--{{ size|default:'full' }}" role="img" aria-label="Fase atual: {{ perfil.fase_atual.nome }} &middot; Status: {{ perfil.get_status_display }}">
    {% for fase_value in fases_ordenadas %}
        <div class="pipeline-track__step{% if fase_value == perfil.fase_atual %}{% if perfil.is_concluido %} is-done{% else %} is-current{% if perfil.status != 'ativo' %} is-current--{{ perfil.status|badge_color }}{% endif %}{% endif %}{% elif fase_value in perfil.fases_concluidas %} is-done{% endif %}" title="{{ fase_value.nome }}{% if fase_value == perfil.fase_atual and perfil.status != 'ativo' %} — {{ perfil.get_status_display }}{% endif %}">
            <span class="pipeline-track__node"></span>
            {% if size != 'mini' %}<span class="pipeline-track__label">{{ fase_value.nome }}</span>{% endif %}
        </div>
    {% endfor %}
</div>
```

- [ ] **Step 4: Update `templates/profiles/_advance_modal.html`**

Change `{{ perfil.get_fase_atual_display }}` to `{{ perfil.fase_atual.nome }}` and `{{ perfil.proxima_fase.label }}` to `{{ perfil.proxima_fase.nome }}`:

```html
                    {% if perfil.proxima_fase %}
                        <div class="phase-transition">
                            <span class="phase-transition__chip">{{ perfil.fase_atual.nome }}</span>
                            <i class="ph-bold ph-arrow-right phase-transition__arrow"></i>
                            <span class="phase-transition__chip phase-transition__chip--next">{{ perfil.proxima_fase.nome }}</span>
                        </div>
```

(Leave the rest of the file unchanged — only those two variable references change.)

- [ ] **Step 5: Update `templates/profiles/profile_list.html`, `profile_detail.html`, `profile_form.html`**

In `templates/profiles/profile_list.html` line 61, change:

```html
                        <div class="text-muted small mt-1">{{ perfil.get_fase_atual_display }}</div>
```

to:

```html
                        <div class="text-muted small mt-1">{{ perfil.fase_atual.nome }}</div>
```

In `templates/profiles/profile_detail.html` line 34, change:

```html
            <div class="fw-semibold mt-1">{{ perfil.get_fase_atual_display }}</div>
```

to:

```html
            <div class="fw-semibold mt-1">{{ perfil.fase_atual.nome }}</div>
```

In the same file, line 151, change:

```html
                            <span class="fw-semibold">{{ item.get_fase_display }}</span>
```

to:

```html
                            <span class="fw-semibold">{{ item.fase_nome }}</span>
```

In `templates/profiles/profile_form.html` line 76, change:

```html
                    A fase atual (<strong>{{ perfil.get_fase_atual_display }}</strong>) é alterada pela ação
```

to:

```html
                    A fase atual (<strong>{{ perfil.fase_atual.nome }}</strong>) é alterada pela ação
```

- [ ] **Step 6: Update `templates/profiles/dashboard.html`**

Change line 80 from:

```html
                        <td class="text-muted small">{{ perfil.get_fase_atual_display }}</td>
```

to:

```html
                        <td class="text-muted small">{{ perfil.fase_atual.nome }}</td>
```

In the `<script>` block, change the funnel-label-parsing line — from:

```javascript
        var funilLabels = chartData.funil.map(function (item) { return item.fase; });
        var funilNumeros = funilLabels.map(function (label) { return label.split('.')[0]; });
```

to:

```javascript
        var funilLabels = chartData.funil.map(function (item) { return item.fase; });
        var funilNumeros = chartData.funil.map(function (item) { return String(item.ordem); });
```

- [ ] **Step 7: Run tests to verify green**

Run: `python manage.py test profiles.tests -v 2`
Expected: PASS (all tests from Tasks 1–3).

- [ ] **Step 8: Commit**

```bash
git add templates/profiles/_pipeline_track.html templates/profiles/_advance_modal.html templates/profiles/profile_list.html templates/profiles/profile_detail.html templates/profiles/profile_form.html templates/profiles/dashboard.html profiles/tests.py
git commit -m "fix: update templates to read PipelineStage.nome instead of Phase choice labels"
```

---

## Task 4: "Configurar pipeline" views and URLs

**Files:**
- Modify: `profiles/forms.py`
- Modify: `profiles/views.py`
- Modify: `profiles/urls.py`
- Test: `profiles/tests.py`

**Interfaces:**
- Consumes: `PipelineStage.excluir_e_realocar()` and `PipelineStage.reordenar()` from Task 1.
- Produces: URL names `profiles:pipeline_configure`, `profiles:pipeline_stage_create`, `profiles:pipeline_stage_rename`, `profiles:pipeline_stage_delete`, `profiles:pipeline_stage_reorder`. `PipelineStageForm(forms.ModelForm)` with a single `nome` field.

- [ ] **Step 1: Write failing tests**

Append to `profiles/tests.py`:

```python
class PipelineConfigureViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa3', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa3', password='senha-forte-123')

    def test_pipeline_configure_lista_fases_na_ordem(self):
        resp = self.client.get(reverse('profiles:pipeline_configure'))
        self.assertEqual(resp.status_code, 200)
        stages = list(resp.context['stages'])
        self.assertEqual([s.ordem for s in stages], list(range(1, 8)))

    def test_criar_fase_adiciona_na_ultima_posicao(self):
        self.client.post(reverse('profiles:pipeline_stage_create'), {'nome': 'Nova fase'})
        nova = PipelineStage.objects.get(nome='Nova fase')
        self.assertEqual(nova.ordem, 8)

    def test_renomear_fase_via_post(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        self.client.post(reverse('profiles:pipeline_stage_rename', args=[stage.pk]), {'nome': 'Renomeada'})
        stage.refresh_from_db()
        self.assertEqual(stage.nome, 'Renomeada')

    def test_apagar_fase_do_meio_move_perfis_e_redireciona(self):
        segunda = PipelineStage.objects.order_by('ordem')[1]
        perfil = Profile.objects.create(nome='Alvo', email='a@example.com', senha='x', fase_atual=segunda)

        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[segunda.pk]), follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PipelineStage.objects.filter(pk=segunda.pk).exists())
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual.ordem, 1)

    def test_apagar_ultima_fase_restante_mostra_erro(self):
        PipelineStage.objects.exclude(pk=PipelineStage.objects.order_by('ordem').first().pk).delete()
        ultima = PipelineStage.objects.get()

        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[ultima.pk]), follow=True)

        self.assertTrue(PipelineStage.objects.filter(pk=ultima.pk).exists())
        self.assertContains(resp, 'não é possível apagar a última fase restante do pipeline'.encode('utf-8').decode('utf-8'), status_code=200) if False else None
        messages = list(resp.context['messages'])
        self.assertTrue(any('última fase' in str(m) for m in messages))

    def test_reordenar_via_post_persiste_nova_ordem(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        nova_ordem_pks = [s.pk for s in reversed(stages)]

        resp = self.client.post(reverse('profiles:pipeline_stage_reorder'), {'pk': nova_ordem_pks})

        self.assertEqual(resp.status_code, 200)
        primeira = PipelineStage.objects.order_by('ordem').first()
        self.assertEqual(primeira.pk, nova_ordem_pks[0])
```

(Note: the odd `if False else None` line above is dead — remove it; it's a leftover from drafting and must not ship. The real assertion is the `messages` check that follows it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test profiles.tests.PipelineConfigureViewTests -v 2`
Expected: FAIL — `NoReverseMatch` for all five URL names (none exist yet).

- [ ] **Step 3: Add `PipelineStageForm` to `profiles/forms.py`**

Append at the end of `profiles/forms.py`:

```python
class PipelineStageForm(forms.ModelForm):
    class Meta:
        model = PipelineStage
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
        }
```

- [ ] **Step 4: Add pipeline-configuration views to `profiles/views.py`**

Change the top imports — from:

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import PhaseAdvanceForm, ProfileFilterForm, ProfileForm
from .models import PipelineStage, Profile, ProfileStatus
```

to:

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import PhaseAdvanceForm, PipelineStageForm, ProfileFilterForm, ProfileForm
from .models import PipelineStage, Profile, ProfileStatus
```

Append at the end of `profiles/views.py`:

```python
@login_required
def pipeline_configure(request):
    stages = PipelineStage.objects.order_by('ordem').annotate(total_perfis=Count('perfis'))
    return render(request, 'profiles/pipeline_configure.html', {'stages': stages})


@login_required
@require_POST
def pipeline_stage_create(request):
    proxima_ordem = (PipelineStage.objects.aggregate(m=Max('ordem'))['m'] or 0) + 1
    form = PipelineStageForm(request.POST)
    if form.is_valid():
        stage = form.save(commit=False)
        stage.ordem = proxima_ordem
        stage.save()
        messages.success(request, f'Fase "{stage.nome}" adicionada.')
    else:
        messages.error(request, 'Informe um nome para a nova fase.')
    return redirect('profiles:pipeline_configure')


@login_required
@require_POST
def pipeline_stage_rename(request, pk):
    stage = get_object_or_404(PipelineStage, pk=pk)
    form = PipelineStageForm(request.POST, instance=stage)
    if form.is_valid():
        form.save()
        messages.success(request, 'Fase renomeada.')
    else:
        messages.error(request, 'Informe um nome para a fase.')
    return redirect('profiles:pipeline_configure')


@login_required
@require_POST
def pipeline_stage_delete(request, pk):
    stage = get_object_or_404(PipelineStage, pk=pk)
    nome = stage.nome
    try:
        stage.excluir_e_realocar(usuario=request.user)
        messages.success(request, f'Fase "{nome}" removida.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('profiles:pipeline_configure')


@login_required
@require_POST
def pipeline_stage_reorder(request):
    pks = [int(pk) for pk in request.POST.getlist('pk')]
    PipelineStage.reordenar(pks)
    return JsonResponse({'ok': True})
```

- [ ] **Step 5: Add URL patterns to `profiles/urls.py`**

```python
from django.urls import path

from . import views

app_name = 'profiles'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('perfis/', views.profile_list, name='profile_list'),
    path('perfis/novo/', views.profile_create, name='profile_create'),
    path('perfis/<int:pk>/', views.profile_detail, name='profile_detail'),
    path('perfis/<int:pk>/editar/', views.profile_update, name='profile_update'),
    path('perfis/<int:pk>/avancar-fase/', views.profile_advance_phase, name='profile_advance_phase'),
    path('pipeline/', views.pipeline_configure, name='pipeline_configure'),
    path('pipeline/criar/', views.pipeline_stage_create, name='pipeline_stage_create'),
    path('pipeline/<int:pk>/renomear/', views.pipeline_stage_rename, name='pipeline_stage_rename'),
    path('pipeline/<int:pk>/apagar/', views.pipeline_stage_delete, name='pipeline_stage_delete'),
    path('pipeline/reordenar/', views.pipeline_stage_reorder, name='pipeline_stage_reorder'),
    path('api/dashboard-data/', views.api_dashboard_data, name='api_dashboard_data'),
]
```

- [ ] **Step 6: This step intentionally left as a correction step — remove the dead line from Step 1's test**

Before running tests, edit `profiles/tests.py` to delete this line from `test_apagar_ultima_fase_restante_mostra_erro` (it was written as a placeholder during drafting and does nothing useful):

```python
        self.assertContains(resp, 'não é possível apagar a última fase restante do pipeline'.encode('utf-8').decode('utf-8'), status_code=200) if False else None
```

The test should read, in full:

```python
    def test_apagar_ultima_fase_restante_mostra_erro(self):
        PipelineStage.objects.exclude(pk=PipelineStage.objects.order_by('ordem').first().pk).delete()
        ultima = PipelineStage.objects.get()

        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[ultima.pk]), follow=True)

        self.assertTrue(PipelineStage.objects.filter(pk=ultima.pk).exists())
        messages_list = list(resp.context['messages'])
        self.assertTrue(any('última fase' in str(m) for m in messages_list))
```

There will be a template rendering error at this point (`profiles/pipeline_configure.html` doesn't exist yet) — that's expected; Task 5 adds it. To get Task 4's tests green in isolation, temporarily confirm the view logic via `pipeline_stage_create`/`rename`/`delete`/`reorder` tests only (they all `redirect` and don't render `pipeline_configure.html` directly except through the `follow=True` GET that lands on it). Since `follow=True` will hit the not-yet-existing template, run Step 7 with a minimal placeholder template first.

- [ ] **Step 7: Add a minimal placeholder template so redirects resolve**

Create `templates/profiles/pipeline_configure.html` with a minimal body (Task 5 replaces this with the full drag-and-drop UI):

```html
{% extends 'base.html' %}
{% block title %}Configurar pipeline{% endblock %}
{% block content %}
<h1>Configurar pipeline</h1>
{% endblock %}
```

- [ ] **Step 8: Run tests to verify green**

Run: `python manage.py test profiles.tests -v 2`
Expected: PASS (all tests from Tasks 1–4).

- [ ] **Step 9: Commit**

```bash
git add profiles/forms.py profiles/views.py profiles/urls.py profiles/tests.py templates/profiles/pipeline_configure.html
git commit -m "feat: add pipeline stage CRUD and reorder views"
```

---

## Task 5: "Configurar pipeline" template — drag-and-drop UI, rename, add, delete

**Files:**
- Modify: `templates/profiles/pipeline_configure.html` (replace placeholder from Task 4)
- Modify: `templates/base.html` (sidebar nav link + CSS)

**Interfaces:**
- Consumes: `stages` context (annotated with `.total_perfis`) from `pipeline_configure` view (Task 4); URL names from Task 4.
- Produces: nothing consumed by later tasks (final UI task).

- [ ] **Step 1: Replace `templates/profiles/pipeline_configure.html`**

```html
{% extends 'base.html' %}
{% load profile_extras %}
{% block title %}Configurar pipeline{% endblock %}
{% block content %}
<div class="page-header">
    <div>
        <p class="page-header__eyebrow">Pipeline</p>
        <h1 class="page-header__title">Configurar pipeline</h1>
    </div>
</div>

<div class="card mb-3">
    <div class="card-body">
        <h6 class="card-title mb-3"><span class="section-icon"><i class="ph-bold ph-flow-arrow"></i></span> Fases (arraste para reordenar)</h6>
        <ul class="pipeline-config-list" id="pipelineStageList">
            {% for stage in stages %}
            <li class="pipeline-config-list__item" data-pk="{{ stage.pk }}">
                <span class="pipeline-config-list__handle" aria-hidden="true"><i class="ph-bold ph-dots-six-vertical"></i></span>
                <form class="pipeline-config-list__rename-form" method="post" action="{% url 'profiles:pipeline_stage_rename' stage.pk %}">
                    {% csrf_token %}
                    <input type="text" name="nome" value="{{ stage.nome }}" class="form-control form-control-sm pipeline-config-list__input" readonly>
                    <button type="button" class="btn btn-sm btn-outline-ink pipeline-config-list__edit" aria-label="Renomear {{ stage.nome }}">
                        <i class="ph-bold ph-pencil-simple"></i>
                    </button>
                    <button type="submit" class="btn btn-sm btn-brand pipeline-config-list__save d-none">Salvar</button>
                </form>
                <span class="pipeline-config-list__count text-muted small">{{ stage.total_perfis }} perfil{{ stage.total_perfis|pluralize }}</span>
                <button type="button" class="btn btn-sm btn-outline-ink pipeline-config-list__delete"
                    data-bs-toggle="modal" data-bs-target="#deleteStageModal{{ stage.pk }}"
                    {% if stages|length <= 1 %}disabled{% endif %}
                    aria-label="Apagar {{ stage.nome }}">
                    <i class="ph-bold ph-trash"></i>
                </button>
            </li>
            {% endfor %}
        </ul>
    </div>
</div>

<div class="card">
    <div class="card-body">
        <h6 class="card-title mb-3"><span class="section-icon"><i class="ph-bold ph-plus-circle"></i></span> Adicionar fase</h6>
        <form method="post" action="{% url 'profiles:pipeline_stage_create' %}" class="d-flex gap-2">
            {% csrf_token %}
            <input type="text" name="nome" class="form-control" placeholder="Nome da nova fase" required>
            <button type="submit" class="btn btn-brand text-nowrap"><i class="ph-bold ph-plus"></i> Adicionar</button>
        </form>
    </div>
</div>

{% for stage in stages %}
<div class="modal fade" id="deleteStageModal{{ stage.pk }}" tabindex="-1" aria-labelledby="deleteStageModalLabel{{ stage.pk }}" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
            <form method="post" action="{% url 'profiles:pipeline_stage_delete' stage.pk %}">
                {% csrf_token %}
                <div class="modal-header">
                    <h5 class="modal-title" id="deleteStageModalLabel{{ stage.pk }}">
                        <span class="modal-icon-badge"><i class="ph-bold ph-trash"></i></span>
                        Apagar fase
                    </h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fechar"></button>
                </div>
                <div class="modal-body">
                    <p>Apagar <strong>{{ stage.nome }}</strong>?</p>
                    {% if stage.total_perfis %}
                    <p class="text-muted small mb-0">
                        {{ stage.total_perfis }} perfil{{ stage.total_perfis|pluralize }} nesta fase
                        {{ stage.total_perfis|pluralize:'será,serão' }} movido{{ stage.total_perfis|pluralize }}
                        para a fase vizinha automaticamente, com registro no histórico.
                    </p>
                    {% endif %}
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-link text-decoration-none" data-bs-dismiss="modal">Cancelar</button>
                    <button type="submit" class="btn btn-brand"><i class="ph-bold ph-trash"></i> Apagar</button>
                </div>
            </form>
        </div>
    </div>
</div>
{% endfor %}
{% endblock %}

{% block extra_js %}
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js" integrity="sha384-BSxuMLxX+FCbTdYec3TbXlnMGEEM2QXTFdtDaveen71o+jswm2J36+xFqp8k4VHM" crossorigin="anonymous"></script>
<script>
document.addEventListener('DOMContentLoaded', function () {
    var list = document.getElementById('pipelineStageList');
    if (!list) return;

    function csrfToken() {
        return list.querySelector('[name=csrfmiddlewaretoken]').value;
    }

    Sortable.create(list, {
        handle: '.pipeline-config-list__handle',
        animation: 150,
        onEnd: function () {
            var pks = Array.prototype.map.call(list.children, function (li) { return li.dataset.pk; });
            var body = new URLSearchParams();
            pks.forEach(function (pk) { body.append('pk', pk); });
            fetch("{% url 'profiles:pipeline_stage_reorder' %}", {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken() },
                body: body,
            });
        }
    });

    list.querySelectorAll('.pipeline-config-list__edit').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var form = btn.closest('form');
            var input = form.querySelector('.pipeline-config-list__input');
            var save = form.querySelector('.pipeline-config-list__save');
            input.readOnly = false;
            input.focus();
            btn.classList.add('d-none');
            save.classList.remove('d-none');
        });
    });
});
</script>
{% endblock %}
```

- [ ] **Step 2: Add CSS to `templates/base.html`**

Insert the following into the `<style>` block in `templates/base.html`, immediately after the `.phase-transition__arrow { color: var(--text-muted); }` rule (around line 528) and before the `/* Auth screen ... */` comment:

```css
        /* Pipeline configuration screen — draggable stage list */
        .pipeline-config-list { list-style: none; margin: 0; padding: 0; }
        .pipeline-config-list__item {
            display: flex;
            align-items: center;
            gap: .75rem;
            padding: .6rem .25rem;
            border-bottom: 1px solid var(--border-subtle);
        }
        .pipeline-config-list__item:last-child { border-bottom: none; }
        .pipeline-config-list__handle { cursor: grab; color: var(--text-muted); flex-shrink: 0; }
        .pipeline-config-list__item.sortable-ghost { opacity: .4; }
        .pipeline-config-list__rename-form { display: flex; align-items: center; gap: .4rem; flex: 1; min-width: 0; }
        .pipeline-config-list__input { border: 1px solid transparent; background: transparent; flex: 1; min-width: 0; }
        .pipeline-config-list__input:not([readonly]) { border-color: var(--border-subtle); background: var(--bg-surface); }
        .pipeline-config-list__count { flex-shrink: 0; white-space: nowrap; }
```

- [ ] **Step 3: Add sidebar nav link in `templates/base.html`**

In the desktop `.sidebar__nav` block, change:

```html
            <a class="sidebar__link{% if request.path == profile_create_url %} is-active{% endif %}" href="{{ profile_create_url }}">
                <i class="ph-bold ph-plus-circle"></i> Novo perfil
            </a>
        </nav>
```

to:

```html
            <a class="sidebar__link{% if request.path == profile_create_url %} is-active{% endif %}" href="{{ profile_create_url }}">
                <i class="ph-bold ph-plus-circle"></i> Novo perfil
            </a>
            <a class="sidebar__link{% if '/pipeline/' in request.path %} is-active{% endif %}" href="{% url 'profiles:pipeline_configure' %}">
                <i class="ph-bold ph-flow-arrow"></i> Configurar pipeline
            </a>
        </nav>
```

And in the mobile `#mobileNav` offcanvas block, change:

```html
                    <a class="sidebar__link{% if request.path == profile_create_url %} is-active{% endif %}" href="{{ profile_create_url }}"><i class="ph-bold ph-plus-circle"></i> Novo perfil</a>
                </nav>
```

to:

```html
                    <a class="sidebar__link{% if request.path == profile_create_url %} is-active{% endif %}" href="{{ profile_create_url }}"><i class="ph-bold ph-plus-circle"></i> Novo perfil</a>
                    <a class="sidebar__link{% if '/pipeline/' in request.path %} is-active{% endif %}" href="{% url 'profiles:pipeline_configure' %}"><i class="ph-bold ph-flow-arrow"></i> Configurar pipeline</a>
                </nav>
```

- [ ] **Step 4: Write a smoke test for the sidebar link**

Append to `profiles/tests.py`:

```python
class PipelineSidebarLinkTests(TestCase):
    def test_sidebar_tem_link_configurar_pipeline(self):
        user = User.objects.create_user(username='qa4', password='senha-forte-123')
        client = Client()
        client.login(username='qa4', password='senha-forte-123')
        resp = client.get(reverse('profiles:dashboard'))
        self.assertContains(resp, reverse('profiles:pipeline_configure'))
        self.assertContains(resp, 'Configurar pipeline')
```

- [ ] **Step 5: Run the full test suite**

Run: `python manage.py test profiles -v 2`
Expected: PASS — every test from Tasks 1 through 5.

- [ ] **Step 6: Manual browser verification (required — do not skip)**

Automated tests cannot exercise drag-and-drop JS. Start the dev server and verify by hand using the `designreview` QA account (see project memory for credentials):

```bash
python manage.py runserver
```

Using the browser (Playwright MCP or manual):
1. Log in, click "Configurar pipeline" in the sidebar — confirm it's now discoverable (this was the original complaint).
2. Drag a stage to a new position, reload the page, confirm the new order persisted.
3. Click the pencil icon on a stage, rename it, submit, confirm the new name shows in the list, on the dashboard funnel, and on any profile's pipeline track.
4. Add a new stage, confirm it appears at the end of the list.
5. Delete a middle stage that has profiles assigned to it, confirm the confirmation modal shows the affected profile count, confirm on a test profile's detail page that its audit history now shows an automatic "movido" entry.
6. Delete stages down to 1 remaining, confirm the delete button is disabled server-side (POST directly via the modal is blocked / shows the error message) and disabled in the UI.
7. Toggle dark mode, confirm the new list/CSS reads correctly in both themes.

- [ ] **Step 7: Commit**

```bash
git add templates/profiles/pipeline_configure.html templates/base.html profiles/tests.py
git commit -m "feat: add drag-and-drop pipeline configuration UI and sidebar entry"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-07-31-editable-pipeline-design.md` maps to a task — data model (Task 1), "Reflexos no restante do app" list (Tasks 2–3, each bullet from the spec's list is addressed individually above), "Tela Configurar pipeline" (Tasks 4–5), "Exclusão de fase com perfis" (Task 1's `excluir_e_realocar` + Task 4's delete view/tests), reorder persistence (Task 1's `reordenar` + Task 5's Sortable.js wiring), "pipeline nunca fica vazio" (Task 1 raises `ValueError`, Task 4 catches and messages it, Task 5 disables the button when `stages|length <= 1`).
- **Known rough edge:** Task 4 Step 1 intentionally includes one dead/broken line in a drafted test (flagged inline) that Step 6 immediately corrects before tests are run — this mirrors how the plan was actually derived and is called out explicitly so whoever executes it doesn't ship the placeholder line.
