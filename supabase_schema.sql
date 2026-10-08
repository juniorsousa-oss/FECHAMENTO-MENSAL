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


-- Histórico alimentado por relatório analítico de estoque.
create table if not exists public.fm_importacoes (
  competencia date primary key,
  arquivo_nome text not null,
  total_linhas integer not null default 0,
  linhas_validas integer not null default 0,
  linhas_invalidas integer not null default 0,
  valor_total numeric(18,2) not null default 0,
  status text not null default 'VALIDO',
  importado_em timestamptz not null default now()
);

create table if not exists public.fm_estoque_itens (
  competencia date not null,
  codigo text not null,
  tp text not null,
  armz text not null,
  saldo numeric(20,6) not null,
  valor_estoque numeric(18,2) not null,
  descricao text not null default '',
  descricao_armazem text not null default '',
  primary key (competencia, codigo, armz)
);

create table if not exists public.fm_estoque_resumos (
  competencia date not null,
  dimensao text not null,
  chave text not null,
  armz text,
  tp text,
  valor_total numeric(18,2) not null default 0,
  itens integer not null default 0,
  primary key (competencia, dimensao, chave)
);

create table if not exists public.fm_importacao_erros (
  id bigserial primary key,
  competencia date not null,
  codigo text,
  tp text,
  armz text,
  saldo numeric(20,6),
  valor_estoque numeric(18,2),
  descricao text not null default '',
  motivo text not null,
  criado_em timestamptz not null default now()
);


-- Histórico mensal dos ajustes de Chapas e Barramentos
create table if not exists public.fm_cb_ajustes_historico (
  competencia date primary key,
  data_fechamento date not null,
  status text not null default 'FINALIZADO',
  itens_ajuste integer not null default 0,
  chapas_entrada_qtd numeric(20,6) not null default 0,
  chapas_saida_qtd numeric(20,6) not null default 0,
  chapas_entrada_valor numeric(18,2) not null default 0,
  chapas_saida_valor numeric(18,2) not null default 0,
  barramentos_entrada_qtd numeric(20,6) not null default 0,
  barramentos_saida_qtd numeric(20,6) not null default 0,
  barramentos_entrada_valor numeric(18,2) not null default 0,
  barramentos_saida_valor numeric(18,2) not null default 0,
  previsao_valor_liquido numeric(18,2) not null default 0,
  previsao_valor_movimentado numeric(18,2) not null default 0,
  finalizado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create table if not exists public.fm_cb_ajustes_itens (
  competencia date not null,
  codigo text not null,
  categoria text not null,
  descricao text not null default '',
  um text not null default '',
  saldo_fechamento numeric(20,6) not null default 0,
  saldo_atual numeric(20,6),
  saldo_base_ajuste numeric(20,6),
  base_origem text not null default '',
  fisico numeric(20,6),
  contagem_assumida_zero boolean not null default false,
  diferenca_qtd numeric(20,6) not null default 0,
  custo_unitario numeric(20,6) not null default 0,
  previsao_valor numeric(18,2) not null default 0,
  finalizado_em timestamptz not null default now(),
  primary key (competencia, codigo)
);

alter table public.fm_cb_ajustes_itens
  add column if not exists saldo_atual numeric(20,6),
  add column if not exists saldo_base_ajuste numeric(20,6),
  add column if not exists base_origem text not null default '',
  add column if not exists contagem_assumida_zero boolean not null default false;

alter table public.fm_cb_ajustes_historico enable row level security;
alter table public.fm_cb_ajustes_itens enable row level security;

drop policy if exists fm_cb_ajustes_historico_read on public.fm_cb_ajustes_historico;
create policy fm_cb_ajustes_historico_read
on public.fm_cb_ajustes_historico
for select
to anon, authenticated
using (true);

drop policy if exists fm_cb_ajustes_itens_read on public.fm_cb_ajustes_itens;
create policy fm_cb_ajustes_itens_read
on public.fm_cb_ajustes_itens
for select
to anon, authenticated
using (true);

create or replace function public.fm_cb_finalizar_ajustes(
  p_competencia date,
  p_data_fechamento date,
  p_rows jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_competencia date := date_trunc('month', p_competencia)::date;
  v_rows jsonb := coalesce(p_rows, '[]'::jsonb);
  v_itens integer := 0;
  v_chapas_entrada_qtd numeric := 0;
  v_chapas_saida_qtd numeric := 0;
  v_chapas_entrada_valor numeric := 0;
  v_chapas_saida_valor numeric := 0;
  v_barras_entrada_qtd numeric := 0;
  v_barras_saida_qtd numeric := 0;
  v_barras_entrada_valor numeric := 0;
  v_barras_saida_valor numeric := 0;
  v_valor_liquido numeric := 0;
  v_valor_movimentado numeric := 0;
begin
  delete from public.fm_cb_ajustes_itens
  where competencia = v_competencia;

  insert into public.fm_cb_ajustes_itens(
    competencia, codigo, categoria, descricao, um,
    saldo_fechamento, saldo_atual, saldo_base_ajuste, base_origem,
    fisico, contagem_assumida_zero, diferenca_qtd,
    custo_unitario, previsao_valor, finalizado_em
  )
  select
    v_competencia,
    trim(coalesce(x.codigo, '')),
    upper(trim(coalesce(x.categoria, ''))),
    coalesce(x.descricao, ''),
    upper(trim(coalesce(x.um, ''))),
    coalesce(x.saldo_fechamento, 0),
    x.saldo_atual,
    coalesce(x.saldo_base_ajuste, x.saldo_fechamento, 0),
    upper(trim(coalesce(x.base_origem, ''))),
    x.fisico,
    coalesce(x.contagem_assumida_zero, false),
    coalesce(x.diferenca_qtd, 0),
    coalesce(x.custo_unitario, 0),
    coalesce(x.previsao_valor, 0),
    now()
  from jsonb_to_recordset(v_rows) as x(
    codigo text,
    categoria text,
    descricao text,
    um text,
    saldo_fechamento numeric,
    saldo_atual numeric,
    saldo_base_ajuste numeric,
    base_origem text,
    fisico numeric,
    contagem_assumida_zero boolean,
    diferenca_qtd numeric,
    custo_unitario numeric,
    previsao_valor numeric
  )
  where trim(coalesce(x.codigo, '')) <> '';

  select
    count(*) filter (where abs(coalesce(diferenca_qtd, 0)) > 1e-9),
    coalesce(sum(case when categoria = 'CHAPA' and diferenca_qtd > 0 then diferenca_qtd else 0 end), 0),
    coalesce(sum(case when categoria = 'CHAPA' and diferenca_qtd < 0 then abs(diferenca_qtd) else 0 end), 0),
    coalesce(sum(case when categoria = 'CHAPA' and previsao_valor > 0 then previsao_valor else 0 end), 0),
    coalesce(sum(case when categoria = 'CHAPA' and previsao_valor < 0 then abs(previsao_valor) else 0 end), 0),
    coalesce(sum(case when categoria = 'BARRA DE COBRE' and diferenca_qtd > 0 then diferenca_qtd else 0 end), 0),
    coalesce(sum(case when categoria = 'BARRA DE COBRE' and diferenca_qtd < 0 then abs(diferenca_qtd) else 0 end), 0),
    coalesce(sum(case when categoria = 'BARRA DE COBRE' and previsao_valor > 0 then previsao_valor else 0 end), 0),
    coalesce(sum(case when categoria = 'BARRA DE COBRE' and previsao_valor < 0 then abs(previsao_valor) else 0 end), 0),
    coalesce(sum(previsao_valor), 0),
    coalesce(sum(abs(previsao_valor)), 0)
  into
    v_itens,
    v_chapas_entrada_qtd,
    v_chapas_saida_qtd,
    v_chapas_entrada_valor,
    v_chapas_saida_valor,
    v_barras_entrada_qtd,
    v_barras_saida_qtd,
    v_barras_entrada_valor,
    v_barras_saida_valor,
    v_valor_liquido,
    v_valor_movimentado
  from public.fm_cb_ajustes_itens
  where competencia = v_competencia;

  insert into public.fm_cb_ajustes_historico(
    competencia, data_fechamento, status, itens_ajuste,
    chapas_entrada_qtd, chapas_saida_qtd,
    chapas_entrada_valor, chapas_saida_valor,
    barramentos_entrada_qtd, barramentos_saida_qtd,
    barramentos_entrada_valor, barramentos_saida_valor,
    previsao_valor_liquido, previsao_valor_movimentado,
    finalizado_em, atualizado_em
  )
  values (
    v_competencia, p_data_fechamento, 'FINALIZADO', v_itens,
    v_chapas_entrada_qtd, v_chapas_saida_qtd,
    v_chapas_entrada_valor, v_chapas_saida_valor,
    v_barras_entrada_qtd, v_barras_saida_qtd,
    v_barras_entrada_valor, v_barras_saida_valor,
    v_valor_liquido, v_valor_movimentado,
    now(), now()
  )
  on conflict (competencia) do update set
    data_fechamento = excluded.data_fechamento,
    status = excluded.status,
    itens_ajuste = excluded.itens_ajuste,
    chapas_entrada_qtd = excluded.chapas_entrada_qtd,
    chapas_saida_qtd = excluded.chapas_saida_qtd,
    chapas_entrada_valor = excluded.chapas_entrada_valor,
    chapas_saida_valor = excluded.chapas_saida_valor,
    barramentos_entrada_qtd = excluded.barramentos_entrada_qtd,
    barramentos_saida_qtd = excluded.barramentos_saida_qtd,
    barramentos_entrada_valor = excluded.barramentos_entrada_valor,
    barramentos_saida_valor = excluded.barramentos_saida_valor,
    previsao_valor_liquido = excluded.previsao_valor_liquido,
    previsao_valor_movimentado = excluded.previsao_valor_movimentado,
    finalizado_em = now(),
    atualizado_em = now();

  return jsonb_build_object(
    'ok', true,
    'competencia', v_competencia,
    'itens_ajuste', v_itens,
    'previsao_valor_liquido', v_valor_liquido,
    'previsao_valor_movimentado', v_valor_movimentado
  );
end;
$$;

grant execute on function public.fm_cb_finalizar_ajustes(date, date, jsonb)
to anon, authenticated;
