from django.contrib import admin

from .models import (
    BusinessManager,
    PageInfo,
    PhaseHistory,
    PipelineStage,
    Profile,
    WhatsAppLink,
)


class PhaseHistoryInline(admin.TabularInline):
    model = PhaseHistory
    extra = 0
    readonly_fields = ('fase_nome', 'data_hora', 'usuario', 'observacao')
    can_delete = False
    ordering = ('-data_hora',)

    def has_add_permission(self, request, obj=None):
        return False


class PageInfoInline(admin.StackedInline):
    model = PageInfo
    extra = 0


class WhatsAppLinkInline(admin.TabularInline):
    model = WhatsAppLink
    extra = 0


class BusinessManagerInline(admin.StackedInline):
    model = BusinessManager
    extra = 0


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        'nome',
        'email',
        'fase_atual',
        'status',
        'adspower_id',
        'responsavel',
        'atualizado_em',
    )
    list_filter = ('fase_atual', 'status', 'tipo_autenticacao')
    search_fields = ('nome', 'email', 'adspower_id')
    autocomplete_fields = ('responsavel',)
    readonly_fields = ('criado_em', 'atualizado_em')
    date_hierarchy = 'criado_em'
    fieldsets = (
        ('Identificação', {
            'fields': ('nome', 'email', 'adspower_id', 'responsavel'),
        }),
        ('Credenciais (criptografadas)', {
            'fields': ('senha', 'tipo_autenticacao', 'dados_autenticacao'),
        }),
        ('Andamento', {
            'fields': ('fase_atual', 'status'),
        }),
        ('Notas', {
            'fields': ('observacoes',),
        }),
        ('Datas', {
            'fields': ('criado_em', 'atualizado_em'),
        }),
    )
    inlines = [PageInfoInline, WhatsAppLinkInline, BusinessManagerInline, PhaseHistoryInline]


@admin.register(PhaseHistory)
class PhaseHistoryAdmin(admin.ModelAdmin):
    list_display = ('perfil', 'fase_nome', 'data_hora', 'usuario')
    list_filter = ('fase_nome',)
    search_fields = ('perfil__nome', 'perfil__email')
    autocomplete_fields = ('perfil', 'usuario')
    date_hierarchy = 'data_hora'


@admin.register(PageInfo)
class PageInfoAdmin(admin.ModelAdmin):
    list_display = ('nome_pagina', 'perfil', 'status', 'data_criacao')
    list_filter = ('status',)
    search_fields = ('nome_pagina', 'perfil__nome')
    autocomplete_fields = ('perfil',)


@admin.register(WhatsAppLink)
class WhatsAppLinkAdmin(admin.ModelAdmin):
    list_display = ('numero_telefone', 'perfil', 'status', 'data_vinculo')
    list_filter = ('status',)
    search_fields = ('numero_telefone', 'perfil__nome')
    autocomplete_fields = ('perfil',)


@admin.register(BusinessManager)
class BusinessManagerAdmin(admin.ModelAdmin):
    list_display = ('nome_bm', 'bm_id', 'perfil', 'status', 'data_geracao')
    list_filter = ('status',)
    search_fields = ('nome_bm', 'bm_id', 'perfil__nome')
    autocomplete_fields = ('perfil',)


@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ordem')
    ordering = ('ordem',)
