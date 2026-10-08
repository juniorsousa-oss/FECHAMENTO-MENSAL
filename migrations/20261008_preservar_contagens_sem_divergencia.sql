-- Mantém o histórico completo de contagens, sem inflar a métrica de ajustes.
-- Linhas com diferença 0 são preservadas para auditoria;
-- itens_ajuste continua contando somente movimentações reais.

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
