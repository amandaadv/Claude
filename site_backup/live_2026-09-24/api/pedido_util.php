<?php
// Helpers compartilhados pelo WebPedido (criar_link_pedido.php + pedido_dados.php
// + pedido.php).
//
// Um link "meu pedido" tem dois modos:
//  - MESCLADO (escopo ''): junta TODOS os pedidos (pendente + validado) da mesma
//    cliente -- mesmo nome (sem diferença de maiúscula/acento/espaço extra) E
//    mesmo telefone (só os dígitos, sem DDI 55). Usado pelo botão da tela de
//    pedidos pendentes.
//  - FOTO DE UMA PRODUÇÃO (escopo 'prod-N' + itens_json): mostra EXATAMENTE a
//    lista que o programa mandou (REF + quantidade de cada figura daquela
//    produção), sem misturar pedidos antigos da mesma cliente. Usado pelo
//    botão de "Produções anteriores" -- lá o que vale é o que foi produzido
//    (a quantidade pode ter sido ajustada em relação ao pedido do site).

function pedido_normalizar_nome(string $nome): string {
    $nome = mb_strtolower(trim($nome), 'UTF-8');
    $comAcento = ['á','à','â','ã','ä','é','è','ê','ë','í','ì','î','ï','ó','ò','ô','õ','ö','ú','ù','û','ü','ç'];
    $semAcento = ['a','a','a','a','a','e','e','e','e','i','i','i','i','o','o','o','o','o','u','u','u','u','c'];
    $nome = str_replace($comAcento, $semAcento, $nome);
    $nome = preg_replace('/\s+/u', ' ', $nome);
    return mb_substr($nome, 0, 120, 'UTF-8');
}

function pedido_normalizar_telefone(string $telefone): string {
    $digitos = preg_replace('/\D+/', '', $telefone);
    // DDI do Brasil digitado à frente (55 + DDD + número = 12/13 dígitos).
    if (strlen($digitos) >= 12 && substr($digitos, 0, 2) === '55') {
        $digitos = substr($digitos, 2);
    }
    return substr($digitos, 0, 32);
}

function pedido_garantir_tabela_links(PDO $pdo): void {
    // Limites de tamanho: o índice único (nome_key + telefone_key + escopo,
    // utf8mb4 = 4 bytes/char) precisa caber nos 767 bytes de índices InnoDB
    // antigos -- 120*4 + 32*4 + 32*4 = 736.
    $pdo->exec("
        CREATE TABLE IF NOT EXISTS pedido_links (
            codigo VARCHAR(64) PRIMARY KEY,
            nome_exibicao VARCHAR(255) NOT NULL,
            nome_key VARCHAR(120) NOT NULL,
            telefone_key VARCHAR(32) NOT NULL,
            escopo VARCHAR(32) NOT NULL DEFAULT '',
            itens_json MEDIUMTEXT NULL,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_cliente_escopo (nome_key, telefone_key, escopo)
        ) DEFAULT CHARSET=utf8mb4
    ");

    // Tabela criada antes dos links por produção existirem: acrescenta as
    // colunas e troca o índice único antigo (só nome+telefone).
    $tem_escopo = $pdo->query("SHOW COLUMNS FROM pedido_links LIKE 'escopo'")->fetch();
    if (!$tem_escopo) {
        try {
            $pdo->exec("ALTER TABLE pedido_links ADD COLUMN escopo VARCHAR(32) NOT NULL DEFAULT ''");
        } catch (Exception $e) {
        }
        try {
            $pdo->exec("ALTER TABLE pedido_links ADD COLUMN itens_json MEDIUMTEXT NULL");
        } catch (Exception $e) {
        }
        try {
            $pdo->exec("ALTER TABLE pedido_links DROP INDEX uq_cliente");
        } catch (Exception $e) {
        }
        try {
            $pdo->exec("ALTER TABLE pedido_links ADD UNIQUE KEY uq_cliente_escopo (nome_key, telefone_key, escopo)");
        } catch (Exception $e) {
        }
    }
}

function pedido_garantir_colunas_produtos(PDO $pdo): void {
    foreach ([
        "ALTER TABLE pedido_itens ADD COLUMN quantidade INT NOT NULL DEFAULT 1",
        "ALTER TABLE pedido_itens ADD COLUMN medida VARCHAR(50) NULL",
        "ALTER TABLE produtos ADD COLUMN imagem_grande_arquivo VARCHAR(255) NULL",
    ] as $sql) {
        try {
            $pdo->exec($sql);
        } catch (Exception $e) {
            // coluna já existe.
        }
    }
}

// MODO MESCLADO: todos os pedidos (pendente + validado; "excluido" nunca
// aparece) dessa cliente, já com os itens. Retorna lista de itens crus (um
// por linha de pedido_itens) -- quem chama agrega como precisar.
function pedido_buscar_itens_da_cliente(PDO $pdo, string $nome_key, string $telefone_key): array {
    pedido_garantir_colunas_produtos($pdo);

    $candidatos = $pdo->query("
        SELECT p.id AS pedido_id, c.nome, c.telefone
        FROM pedidos p JOIN clientes c ON c.id = p.cliente_id
        WHERE p.status IN ('pendente', 'validado')
    ")->fetchAll();

    $pedido_ids = [];
    foreach ($candidatos as $c) {
        if (pedido_normalizar_nome((string)$c['nome']) === $nome_key
            && pedido_normalizar_telefone((string)$c['telefone']) === $telefone_key) {
            $pedido_ids[] = (int)$c['pedido_id'];
        }
    }
    if (count($pedido_ids) === 0) {
        return [];
    }

    // ids são inteiros já convertidos acima -- seguro inline no IN().
    $lista = implode(',', $pedido_ids);
    return $pdo->query("
        SELECT pi.pedido_id, pr.id AS produto_id, pr.catalogo_nome, pr.referencia, pr.nome,
               pr.imagem_arquivo, pr.imagem_grande_arquivo,
               COALESCE(pi.quantidade, 1) AS quantidade, pi.medida
        FROM pedido_itens pi JOIN produtos pr ON pr.id = pi.produto_id
        WHERE pi.pedido_id IN ($lista)
        ORDER BY pr.catalogo_nome, pr.id
    ")->fetchAll();
}

// Limpa/valida a lista de itens vinda do programa (modo FOTO DE PRODUÇÃO).
function pedido_sanear_itens($itens): array {
    $limpos = [];
    if (!is_array($itens)) {
        return $limpos;
    }
    foreach ($itens as $item) {
        if (!is_array($item)) {
            continue;
        }
        $catalogo = trim((string)($item['catalogo_nome'] ?? ''));
        $referencia = trim((string)($item['referencia'] ?? ''));
        $quantidade = (int)($item['quantidade'] ?? 0);
        if ($catalogo === '' || $referencia === '' || $quantidade < 1) {
            continue;
        }
        $medida = trim((string)($item['medida'] ?? ''));
        $limpos[] = [
            'catalogo_nome' => mb_substr($catalogo, 0, 255),
            'referencia'    => mb_substr($referencia, 0, 100),
            'quantidade'    => min($quantidade, 99999),
            'medida'        => $medida !== '' ? mb_substr($medida, 0, 50) : null,
        ];
    }
    return $limpos;
}

// MODO FOTO DE PRODUÇÃO: casa cada item da lista guardada com o produto do
// site (catálogo + REF, mesmo produto já desativado -- a imagem continua lá).
// Retorna [linhas no mesmo formato de pedido_buscar_itens_da_cliente,
// lista dos itens que NÃO existem no site (catálogo nunca publicado etc.)].
function pedido_linhas_do_snapshot(PDO $pdo, $itens_json): array {
    pedido_garantir_colunas_produtos($pdo);
    $itens = json_decode((string)$itens_json, true);
    if (!is_array($itens) || count($itens) === 0) {
        return [[], []];
    }

    $catalogos = array_values(array_unique(array_map(fn($i) => (string)$i['catalogo_nome'], $itens)));
    $marcas = implode(',', array_fill(0, count($catalogos), '?'));
    $stmt = $pdo->prepare("
        SELECT id, catalogo_nome, referencia, nome, imagem_arquivo, imagem_grande_arquivo
        FROM produtos WHERE catalogo_nome IN ($marcas)
    ");
    $stmt->execute($catalogos);
    $por_chave = [];
    foreach ($stmt->fetchAll() as $p) {
        $por_chave[$p['catalogo_nome'] . '|||' . $p['referencia']] = $p;
    }

    $linhas = [];
    $faltando = [];
    foreach ($itens as $item) {
        $p = $por_chave[$item['catalogo_nome'] . '|||' . $item['referencia']] ?? null;
        if (!$p || !$p['imagem_arquivo']) {
            $faltando[] = $item['catalogo_nome'] . ' · ' . $item['referencia'];
            continue;
        }
        $linhas[] = [
            'pedido_id'             => 0, // foto de uma produção só = "1 pedido"
            'produto_id'            => (int)$p['id'],
            'catalogo_nome'         => $p['catalogo_nome'],
            'referencia'            => $p['referencia'],
            'nome'                  => $p['nome'],
            'imagem_arquivo'        => $p['imagem_arquivo'],
            'imagem_grande_arquivo' => $p['imagem_grande_arquivo'],
            'quantidade'            => (int)$item['quantidade'],
            'medida'                => $item['medida'] ?? null,
        ];
    }
    usort($linhas, fn($a, $b) => [$a['catalogo_nome'], $a['produto_id']] <=> [$b['catalogo_nome'], $b['produto_id']]);
    return [$linhas, $faltando];
}

// Resposta completa da página "meu pedido" (usada por pedido_dados.php e
// pelo pedido.php pra montar a prévia do WhatsApp com os mesmos totais).
// $link = linha de pedido_links (nome_exibicao, nome_key, telefone_key, itens_json).
function pedido_dados_do_link(PDO $pdo, array $link): array {
    if (!empty($link['itens_json'])) {
        [$linhas] = pedido_linhas_do_snapshot($pdo, $link['itens_json']);
    } else {
        $linhas = pedido_buscar_itens_da_cliente($pdo, $link['nome_key'], $link['telefone_key']);
    }

    // Mesma figura em pedidos diferentes (ou repetida) vira UM card com a
    // quantidade somada; medida diferente da mesma figura continua card separado.
    $agregado = [];
    $pedidos_distintos = [];
    $catalogos = [];
    $figuras = [];
    $total_pecas = 0;
    foreach ($linhas as $l) {
        $pedidos_distintos[$l['pedido_id']] = true;
        $catalogos[$l['catalogo_nome']] = true;
        $figuras[$l['produto_id']] = true;
        $qtd = (int)$l['quantidade'];
        $total_pecas += $qtd;

        $chave = $l['produto_id'] . '|' . ($l['medida'] ?? '');
        if (!isset($agregado[$chave])) {
            $imagem = '/produtos/' . rawurlencode((string)$l['imagem_arquivo']);
            $agregado[$chave] = [
                'catalogo_nome'     => $l['catalogo_nome'],
                'referencia'        => $l['referencia'],
                'nome'              => $l['nome'],
                'medida'            => $l['medida'],
                'quantidade'        => 0,
                'imagem_url'        => $imagem,
                'imagem_grande_url' => $l['imagem_grande_arquivo']
                    ? '/produtos/' . rawurlencode($l['imagem_grande_arquivo'])
                    : $imagem,
            ];
        }
        $agregado[$chave]['quantidade'] += $qtd;
    }

    return [
        'cliente_nome' => $link['nome_exibicao'],
        'totais' => [
            'pedidos'   => count($pedidos_distintos),
            'pecas'     => $total_pecas,
            'figuras'   => count($figuras),
            'catalogos' => count($catalogos),
        ],
        'produtos' => array_values($agregado),
    ];
}
