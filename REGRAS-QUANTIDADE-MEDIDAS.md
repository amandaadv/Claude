# Regras: quantidade inicial por tipo de produto e medida (catálogo web + sistema)

Passadas pelo dj em 2026-09-24. **Ainda NÃO implementado** — dj vai mandar mais informação antes.

## Problema
No catálogo web a quantidade é fixa em 7 (`QUANTIDADE_MINIMA = 7`, `QUANTIDADE_PASSO = 7` no `index.html`) para
qualquer medida. O certo: cada medida tem a sua quantidade inicial.

## Decisões já confirmadas pelo dj
1. **A quantidade é sempre MÚLTIPLA da quantidade inicial da medida.** "Adicionar" entra com N e o + / − andam de N em N
   (ex.: aplique termo colante 140×120 → 4, 8, 12...; nunca desce abaixo de N).
2. **O dj precisa definir o TIPO de cada catálogo** (termo colante / adesivo / faixa) para a regra funcionar. Sem tipo
   definido, o sistema não sabe qual tabela usar. Onde definir: botão "Tipo" no card do catálogo (tela Catálogos).

## Tabela (unidades presumidas em milímetros — confirmar)

### Aplique — TERMO COLANTE
| Medida | Quantidade inicial | Como escala |
|---|---|---|
| 80 x proporcional | 7 | proporcional |
| 90 x proporcional | 7 | proporcional |
| 110 x 100 | 10 | proporcional |
| 140 x 120 | 4 | **fixa** |

### Aplique — ADESIVO
| Medida | Quantidade inicial | Como escala |
|---|---|---|
| 80 x proporcional | 5 | proporcional |
| 90 x proporcional | 4 | proporcional |
| 110 x 100 | 4 | proporcional |
| 140 x 120 | 3 | **fixa** |

### Faixa — TERMO COLANTE
| Medida | Quantidade inicial |
|---|---|
| 488 x 111 | 5 |
| 290 x 60 | 9 |
| 215 x 50 | 11 |
| 290 x 55 | 10 |
| 215 x 45 | 12 |
| 400 x 111 | 5 |
| 350 x 111 | 5 |
| 290 x 111 | 5 |
| 150 x 60 | 9 |
| 150 x 50 | 10 |

## O que precisa mudar
- **Site** (`index.html`): "Adicionar" começa em N da medida escolhida; + / − de N em N; trocar de medida recalcula.
- **Sistema**: ao aceitar um pedido do site, a produção e o orçamento usam a **medida escolhida pela cliente**
  (hoje `pa.do_validate_website_order` ignora `medida` e usa o tamanho original da figura).
  "Proporcional" = escala mantendo a proporção; "fixa" = exatamente 140×120.

## Dúvidas ainda abertas (assumidas até o dj dizer o contrário)
- Faixas: a medida é o tamanho da própria faixa (cliente não escolhe) e a quantidade inicial sai desse tamanho.
- "110 x 100 proporcional": lado maior 110, lado menor proporcional (máx. 100)?
- Unidade: milímetros.

## Problema achado no caminho
`catalogs.tipo_produto` está gravado errado (`CTkComboBox`, nome de componente da tela) em Baby 01, Baby 02 e Natalinos —
bug ao salvar pelo botão "Tipo" (`gui_page_catalogs.py`, `_set_tipo_produto`). Corrigir junto, senão o tipo não serve.

## Como o card da figura deve funcionar no site (pedido do dj em 2026-09-24)
Hoje cada card só tem um botão "Adicionar" (entra com 7). Novo fluxo, em cada card de figura:
1. Botão **Tipo**: Termo colante | Adesivo.
2. Abaixo, botão **Medida**: mostra só as medidas disponíveis para aquele tipo; a cliente escolhe.
3. O botão **Adicionar** passa a mostrar/usar a **quantidade certa** daquele tipo + medida (múltiplos dela).
4. Ao adicionar, o item vai para o **Carrinho** (a cliente vê os itens que adicionou) e o **card volta ao início**
   (reseta), para ela poder escolher outro tipo/medida da mesma figura ou seguir.
5. **Finalizar** envia o pedido com tudo que está no carrinho.

Impacto: o item do pedido passa a precisar de `tipo` + `medida` + `quantidade`, e a MESMA figura pode aparecer em mais de
uma linha (tipos/medidas diferentes). Site (`index.html`, `finalizar.php`, `pedidos.php`) e sistema (tela de pedidos,
`do_validate_website_order`, produção/orçamento) mudam juntos.

## ESTADO (2026-09-24): feito localmente, AINDA NÃO NO AR — aguardando OK do dj
Prévia com fotos em `site_backup/previa/`. Backup do que estava no ar em `site_backup/live_2026-09-24/`.
Arquivos a enviar ao servidor (FTP em FTP.md), nesta ordem:
1. novos: `api/regras_medidas.json`, `api/regras_medidas.php`, `api/definir_categoria.php`
2. alterados: `api/publicar.php`, `api/finalizar.php`, `api/pedidos.php`, `api/meus_pedidos_representante.php`,
   `api/remover_item_pedido.php`, `api/pedido_util.php`, `api/catalogo_personalizado.php`, `api/catalogo.php`, `index.html`
Sem categoria definida em um catálogo, o site continua no "Adicionar" antigo (7 em 7) — deploy não muda nada até o dj
marcar Aplique/Faixa no botão "Tipo" do card (app). Regras mudam editando `api/regras_medidas.json`.
Limitação: "Gerar de novo" volta com o tamanho do catálogo, não com a medida escolhida no pedido.

## AJUSTES 2026-09-24 (já no ar, em `?teste=1` e nos catálogos classificados)
- Palavra é **Termocolante** (junto), não "termo colante".
- **Aplique termocolante NÃO tem a medida 80** (removida); só 90 (7), 110x100 (10) e 140x120 fixa (4). Adesivo continua com 80 (5).
- Card com botões de Tipo/Medida mostra **só a REF** (sem o "MED 89X90MM" cinza) — também no carrinho e no zoom.
- Depois de Adicionar o card **não fica marcado** (sem borda rosa nem "No carrinho"): volta neutro; só aparece "✓ Adicionado ao carrinho" por ~1,5 s.
- Fluxo do card: botão Tipo (popup) → botão Medida (popup) → quantidade com − / + (múltiplos) → Adicionar ao carrinho.
- Modo de teste: `https://babyluzconfeccao.com.br/?teste=1` (mostra o fluxo novo em todos os catálogos, não envia pedido).

## EM PRODUÇÃO (2026-09-24): catálogos classificados — site normal já usa o fluxo novo
Aplique: BABY 01/02/03/04, APLIQUE FLORAIS, COPA E COZINHA FLORES E FRUTA, APLIQUES DE COZINHA, APLIQUE COPA COZINHA,
APLIQUE NATALINOS, NATALINOS, UMBANDA 1.O (x2), CATÁLOGO UMBANDA, CRIANÇA, FRASES (Professor, Dia das Crianças, Bíblicas,
Personalizadas), ECUMÊNICO.
Faixa: FAIXAS 29,6CM E 111CM, FAIXAS TOALHAS, FLORES E FRUTAS FAIXAS, FAIXAS BABY, BABY FAIXA FLORAL, TOALHAS NATAL COMPLETO.
(Critério: tamanho real das figuras — aplique 80/90/111 mm; faixa 290–488 mm.) Mudar: botão "Tipo" no card do catálogo (app).
Sem categoria no site: nenhuma figura. Catálogo novo publicado sem categoria volta ao "Adicionar" antigo.

## AJUSTE (2026-09-24, produção): medida 110 x 100 é PROPORCIONAL igual ao 90
Lado maior = 110 mm e o outro lado acompanha a proporção da figura (SEM teto de 100). Ex.: figura 90x89 -> 110 x 108,9.
Só a 140 x 120 é "fixa" (exatamente 140x120). Regras em `api/regras_medidas.json` (campo "menor": null = sem teto).
Também corrigido: mesma figura em medidas diferentes no mesmo pedido agora sai cada uma no seu tamanho (cache do
gerador de produção agora inclui o tamanho).

## VALORES ATUAIS (dj atualizou em 2026-09-24 — já no site; a tabela do começo deste arquivo está DESATUALIZADA)
Aplique **Termocolante** (sem 80): 90 = 7 · 110x100 = 10 · 140x120 (fixa) = 6
Aplique **Adesivo**: 80 = 8 · 90 = 7 · 110x100 = 10 · 140x120 (fixa) = 6
**Faixa** Termocolante: 488x111 = 10 · 290x60 = 9 · 215x50 = 11 · 290x55 = 10 · 215x45 = 12 · 400x111 = 10 ·
350x111 = 10 · 290x111 = 10 · 150x60 = 10 · 150x50 = 10
Fonte da verdade: `site_backup/api/regras_medidas.json` (editar e enviar por FTP; o site e a validação do pedido leem dele).

## PRODUÇÃO (2026-09-25)
- Pedido que mistura FAIXA e APLIQUE sai em 2 produções (apliques primeiro, faixas depois); faixa sempre EM PÉ (vertical). Tipo pelo botão "Tipo" do catálogo (sem tipo = aplique).
- Ao terminar a produção, o app fecha os arquivos originais dos catálogos que ele abriu; só a produção fica aberta no CorelDRAW (arquivo que o dj já tinha aberto nunca é fechado).
- Produção sai em sequência de tamanho (todas as 90, depois 110, 140...).
