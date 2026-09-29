# FECHAMENTO MENSAL | SETTA

Aplicativo Streamlit para acompanhamento e análise do fechamento mensal de inventário.

## Módulos

- Dashboard
- Conferência de chapas e barramentos
- Conferência de baixas
- Análise de movimentações
- Configurações

## Dashboard mensal

O Dashboard acompanha por competência:

- estoque inicial e final total;
- S2: estoque inicial, estoque final, baixa de OP, ajustes, compras, transferências/doações/vendas e resumo;
- EP: estoque inicial, estoque final e resumo;
- PA: estoque inicial, estoque final e resumo;
- faturamento;
- variação do estoque;
- histórico mês a mês.

Quando uma nova competência é aberta, os estoques iniciais podem ser sugeridos a partir dos estoques finais do mês anterior.

## Persistência

Os dados mensais e as configurações são persistidos no Supabase. A página e a competência selecionadas são mantidas na URL para sobreviver à atualização do navegador.

O favicon é carregado a partir da identidade visual atualmente salva no aplicativo NFS Setta.
