-- FECHAMENTO MENSAL | SETTA
-- Estrutura persistente do módulo.

create table if not exists public.fm_configuracoes (
  chave text primary key,
  valor jsonb not null default '{}'::jsonb,
  atualizado_em timestamptz not null default now()
);

create table if not exists public.fm_fechamentos_mensais (
  competencia date primary key,
  faturamento numeric(18,2) not null default 0,
  ei_s2 numeric(18,2) not null default 0,
  ef_s2 numeric(18,2) not null default 0,
  baixa_op_s2 numeric(18,2) not null default 0,
  ajustes_s2 numeric(18,2) not null default 0,
  compras_s2 numeric(18,2) not null default 0,
  transferencias_s2 numeric(18,2) not null default 0,
  vendas_s2 numeric(18,2) not null default 0,
  ei_ep numeric(18,2) not null default 0,
  ef_ep numeric(18,2) not null default 0,
  ei_pa numeric(18,2) not null default 0,
  ef_pa numeric(18,2) not null default 0,
  observacao text not null default '',
  atualizado_em timestamptz not null default now()
);

alter table public.fm_configuracoes enable row level security;
alter table public.fm_fechamentos_mensais enable row level security;

drop policy if exists fm_configuracoes_read on public.fm_configuracoes;
create policy fm_configuracoes_read
on public.fm_configuracoes
for select
to anon, authenticated
using (true);

drop policy if exists fm_fechamentos_read on public.fm_fechamentos_mensais;
create policy fm_fechamentos_read
on public.fm_fechamentos_mensais
for select
to anon, authenticated
using (true);

create or replace function public.fm_salvar_configuracao(p_chave text, p_valor jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.fm_configuracoes(chave, valor, atualizado_em)
  values (p_chave, coalesce(p_valor, '{}'::jsonb), now())
  on conflict (chave) do update
    set valor = excluded.valor,
        atualizado_em = now();

  return jsonb_build_object('ok', true, 'chave', p_chave);
end;
$$;

create or replace function public.fm_salvar_fechamento(
  p_competencia date,
  p_faturamento numeric,
  p_ei_s2 numeric,
  p_ef_s2 numeric,
  p_baixa_op_s2 numeric,
  p_ajustes_s2 numeric,
  p_compras_s2 numeric,
  p_transferencias_s2 numeric,
  p_vendas_s2 numeric,
  p_ei_ep numeric,
  p_ef_ep numeric,
  p_ei_pa numeric,
  p_ef_pa numeric,
  p_observacao text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.fm_fechamentos_mensais(
    competencia, faturamento,
    ei_s2, ef_s2, baixa_op_s2, ajustes_s2, compras_s2, transferencias_s2, vendas_s2,
    ei_ep, ef_ep, ei_pa, ef_pa,
    observacao, atualizado_em
  )
  values (
    date_trunc('month', p_competencia)::date,
    coalesce(p_faturamento, 0),
    coalesce(p_ei_s2, 0), coalesce(p_ef_s2, 0),
    coalesce(p_baixa_op_s2, 0), coalesce(p_ajustes_s2, 0),
    coalesce(p_compras_s2, 0), coalesce(p_transferencias_s2, 0),
    coalesce(p_vendas_s2, 0),
    coalesce(p_ei_ep, 0), coalesce(p_ef_ep, 0),
    coalesce(p_ei_pa, 0), coalesce(p_ef_pa, 0),
    coalesce(p_observacao, ''),
    now()
  )
  on conflict (competencia) do update set
    faturamento = excluded.faturamento,
    ei_s2 = excluded.ei_s2,
    ef_s2 = excluded.ef_s2,
    baixa_op_s2 = excluded.baixa_op_s2,
    ajustes_s2 = excluded.ajustes_s2,
    compras_s2 = excluded.compras_s2,
    transferencias_s2 = excluded.transferencias_s2,
    vendas_s2 = excluded.vendas_s2,
    ei_ep = excluded.ei_ep,
    ef_ep = excluded.ef_ep,
    ei_pa = excluded.ei_pa,
    ef_pa = excluded.ef_pa,
    observacao = excluded.observacao,
    atualizado_em = now();

  return jsonb_build_object('ok', true);
end;
$$;

grant execute on function public.fm_salvar_configuracao(text, jsonb) to anon, authenticated;
grant execute on function public.fm_salvar_fechamento(date, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric, text) to anon, authenticated;
