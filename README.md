# FECHAMENTO MENSAL | SETTA

Aplicativo Streamlit para acompanhamento e análise do fechamento mensal de inventário.

## Alimentação do histórico

O histórico mensal é alimentado exclusivamente por relatório analítico de estoque `.xlsx` ou `.xltx`.

Colunas obrigatórias:
- CODIGO
- TP
- ARMZ
- SALDO EM ESTOQUE
- VALOR EM ESTOQUE

A importação é bloqueada quando houver:
- produto sem saldo;
- produto sem custo/valor;
- saldo negativo;
- valor de estoque negativo;
- TP ou ARMZ ausente;
- código duplicado no mesmo armazém.

## Dashboard

Para cada competência o Dashboard apresenta:
- análise total: estoque inicial, estoque final e resumo;
- análise por armazém (ARMZ): inicial, final e resumo;
- análise por tipo de produto (TP): inicial, final e resumo;
- histórico mês a mês.

O estoque inicial de um mês é obtido do estoque final do mês anterior.

## Módulos laterais

- Dashboard
- Conferência de chapas e barramentos
- Conferência de baixas
- Análise de movimentações
- Configurações

As regras de movimentações serão definidas em etapa posterior.

## Persistência

Dados e configurações são persistidos no Supabase. A página e a competência selecionadas permanecem na URL.

### Fechamento: duas bases independentes
- **Kardex consolidado**: em Configurações → Alimentadores → KARDEX, há uma única prévia de S2, EP e E2. A prévia é somente leitura. A aplicação explícita grava uma única revisão da competência em aberto, mantendo a origem e a cobertura de cada armazém. As fontes manuais continuam disponíveis em contingência.
- **OPS**: em Configurações → Alimentadores → OPS, a origem da Conferência de Baixas é conferida e aplicada separadamente. O fluxo não agrega linhas ou valores ao Kardex.
