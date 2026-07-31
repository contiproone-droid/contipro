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


@login_required
def profile_list(request):
    perfis = Profile.objects.select_related('responsavel').all()
    filtro = ProfileFilterForm(request.GET or None)

    if filtro.is_valid():
        busca = filtro.cleaned_data.get('q')
        fase = filtro.cleaned_data.get('fase')
        status = filtro.cleaned_data.get('status')
        if busca:
            perfis = perfis.filter(
                Q(nome__icontains=busca)
                | Q(email__icontains=busca)
                | Q(adspower_id__icontains=busca)
            )
        if fase:
            perfis = perfis.filter(fase_atual=fase)
        if status:
            perfis = perfis.filter(status=status)

    paginator = Paginator(perfis, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'profiles/profile_list.html', {
        'filtro': filtro,
        'page_obj': page_obj,
        'perfis': page_obj.object_list,
    })


@login_required
def profile_create(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            perfil = form.save(commit=False)
            if not perfil.responsavel_id:
                perfil.responsavel = request.user
            perfil.save()
            messages.success(request, f'Perfil "{perfil.nome}" criado com sucesso.')
            return redirect('profiles:profile_detail', pk=perfil.pk)
    else:
        form = ProfileForm(initial={'responsavel': request.user.pk})

    return render(request, 'profiles/profile_form.html', {
        'form': form,
        'titulo': 'Novo Perfil',
    })


@login_required
def profile_update(request, pk):
    perfil = get_object_or_404(Profile, pk=pk)

    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=perfil)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil atualizado com sucesso.')
            return redirect('profiles:profile_detail', pk=perfil.pk)
    else:
        form = ProfileForm(instance=perfil)

    return render(request, 'profiles/profile_form.html', {
        'form': form,
        'titulo': f'Editar Perfil: {perfil.nome}',
        'perfil': perfil,
    })


@login_required
def profile_detail(request, pk):
    perfil = get_object_or_404(
        Profile.objects.select_related('responsavel').prefetch_related(
            'historico_fases__usuario',
            'paginas',
            'whatsapp_links',
            'business_manager',
        ),
        pk=pk,
    )
    business_manager = getattr(perfil, 'business_manager', None)

    return render(request, 'profiles/profile_detail.html', {
        'perfil': perfil,
        'historico': perfil.historico_fases.all(),
        'paginas': perfil.paginas.all(),
        'whatsapp_links': perfil.whatsapp_links.all(),
        'business_manager': business_manager,
    })


@login_required
@require_POST
def profile_advance_phase(request, pk):
    perfil = get_object_or_404(Profile, pk=pk)
    form = PhaseAdvanceForm(request.POST)
    observacao = form.cleaned_data.get('observacao', '') if form.is_valid() else ''

    if perfil.avancar_fase(usuario=request.user, observacao=observacao):
        messages.success(request, f'Perfil avançado para "{perfil.fase_atual.nome}".')
    else:
        messages.info(request, 'Este perfil já está na última fase (Concluído / Ativo).')

    return redirect('profiles:profile_detail', pk=perfil.pk)


@login_required
def dashboard(request):
    total_perfis = Profile.objects.count()
    agora = timezone.localtime()

    ultima_fase = PipelineStage.objects.order_by('-ordem').first()
    concluidos_mes = Profile.objects.filter(
        fase_atual=ultima_fase,
        atualizado_em__year=agora.year,
        atualizado_em__month=agora.month,
    ).count() if ultima_fase else 0
    concluidos_total = Profile.objects.filter(fase_atual=ultima_fase).count() if ultima_fase else 0
    taxa_conversao = (concluidos_total / total_perfis * 100) if total_perfis else 0

    perfis_recentes = Profile.objects.select_related('responsavel').order_by('-atualizado_em')[:10]

    return render(request, 'profiles/dashboard.html', {
        'total_perfis': total_perfis,
        'concluidos_mes': concluidos_mes,
        'concluidos_total': concluidos_total,
        'taxa_conversao': round(taxa_conversao, 1),
        'perfis_recentes': perfis_recentes,
    })


@login_required
def api_dashboard_data(request):
    funil = [
        {'fase': stage.nome, 'ordem': stage.ordem, 'total': Profile.objects.filter(fase_atual=stage).count()}
        for stage in PipelineStage.objects.order_by('ordem')
    ]
    status_data = [
        {'status': label, 'total': Profile.objects.filter(status=value).count()}
        for value, label in ProfileStatus.choices
    ]

    return JsonResponse({'funil': funil, 'status': status_data})
