from django import template

register = template.Library()

PILL_MODIFIERS = {
    'ativo': 'success',
    'criada': 'success',
    'vinculado': 'success',
    'concluido': 'success',
    'pendente': 'warning',
    'suspenso': 'warning',
    'restrito': 'warning',
    'pausado': 'neutral',
    'banido': 'danger',
    'falhou': 'danger',
}


@register.filter
def badge_color(value):
    return PILL_MODIFIERS.get(value, 'neutral')
