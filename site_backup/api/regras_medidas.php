<?php
// Regras de QUANTIDADE por categoria do catálogo + tipo + medida (a tabela que o
// dj passou: aplique termo colante / aplique adesivo / faixa termo colante).
// Os números moram em regras_medidas.json (é só editar lá pra mudar uma
// quantidade). Este arquivo:
//  - responde GET com o JSON (o site usa pra montar os botões de tipo/medida);
//  - quando incluído por outro PHP (require), oferece as funções de consulta
//    usadas pra validar o pedido e escrever os rótulos.

function regras_carregar(): array {
    static $regras = null;
    if ($regras === null) {
        $json = @file_get_contents(__DIR__ . '/regras_medidas.json');
        $regras = $json ? (json_decode($json, true) ?: []) : [];
    }
    return $regras;
}

// Lista de medidas de uma categoria+tipo (ex.: 'aplique','adesivo'); [] se não existir.
function regras_lista(?string $categoria, ?string $tipo): array {
    if (!$categoria || !$tipo) {
        return [];
    }
    return regras_carregar()['categorias'][$categoria]['tipos'][$tipo] ?? [];
}

// Uma medida (pelo id, ex. '110x100') ou null.
function regras_achar(?string $categoria, ?string $tipo, ?string $medida_id): ?array {
    if ($medida_id === null || $medida_id === '') {
        return null;
    }
    foreach (regras_lista($categoria, $tipo) as $m) {
        if ((string)$m['id'] === (string)$medida_id) {
            return $m;
        }
    }
    return null;
}

function regras_rotulo_tipo(?string $tipo): string {
    return regras_carregar()['tipos'][$tipo ?? ''] ?? '';
}

// Arredonda a quantidade pra cima até o múltiplo da quantidade da medida
// (regra do dj: a quantidade é sempre múltipla da inicial, e nunca menor que ela).
function regras_ajustar_quantidade(int $quantidade, int $qtd_medida): int {
    if ($qtd_medida < 1) {
        return max(1, $quantidade);
    }
    return max($qtd_medida, (int)(ceil($quantidade / $qtd_medida) * $qtd_medida));
}

// Texto pra mostrar pra operadora/cliente: "Termo colante · 110 x 100 mm"
// (ou só a medida antiga em texto livre, pra pedido feito antes disso).
function regras_texto_item(?string $categoria, ?string $tipo, ?string $medida): ?string {
    $regra = regras_achar($categoria, $tipo, $medida);
    $partes = [];
    if ($tipo && regras_rotulo_tipo($tipo) !== '') {
        $partes[] = regras_rotulo_tipo($tipo);
    }
    if ($regra) {
        $partes[] = $regra['rotulo'];
    } elseif ($medida !== null && $medida !== '') {
        $partes[] = $medida;
    }
    return $partes ? implode(' · ', $partes) : null;
}

// Chamado direto pelo navegador: devolve o JSON das regras.
if (basename($_SERVER['SCRIPT_NAME'] ?? '') === 'regras_medidas.php') {
    // Mesmo CORS do config.php -- esse arquivo não inclui config.php (pra não
    // correr risco de redeclarar função quando é dado require por quem já
    // deu require em config.php antes), então repete só o necessário aqui.
    $allowed_origins = [
        'https://babyluzconfeccao.com.br',
        'https://www.babyluzconfeccao.com.br',
        'https://pedido.babyluzconfeccao.com.br',
    ];
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    if (in_array($origin, $allowed_origins, true)) {
        header("Access-Control-Allow-Origin: $origin");
    }
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
    echo json_encode(regras_carregar(), JSON_UNESCAPED_UNICODE);
    exit;
}
