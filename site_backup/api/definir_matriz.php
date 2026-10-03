<?php
// Protegido (X-Api-Secret): marca a máquina que está chamando isso AGORA
// como a matriz -- só o que essa máquina publicar passa a aparecer pro
// cliente final em catalogo.php. Identidade vem de get_caller_identity()
// (config.php): o id fixo que o programa manda (X-Machine-Id), com o IP
// só como fallback pra um cliente antigo que ainda não manda esse header.
// Guardado no banco (não em config.local.php), pra dar pra redefinir com 1
// clique no app sem precisar de FTP -- era importante quando isso usava só
// IP (principalmente IPv6, que pode mudar sozinho de vez em quando -- viu
// isso ao vivo quebrar a vitrine mais de uma vez); com o id fixo isso não
// deveria mais ser preciso no dia a dia, mas o botão continua útil pra
// trocar de máquina matriz de propósito.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

$identidade = get_caller_identity();
if ($identidade === '') {
    http_response_code(500);
    echo json_encode(['erro' => 'não consegui identificar essa requisição']);
    exit;
}

$pdo = get_pdo();
$pdo->exec("
    CREATE TABLE IF NOT EXISTS config_site (
        chave VARCHAR(64) PRIMARY KEY,
        valor VARCHAR(255) NOT NULL
    )
");
$stmt = $pdo->prepare("
    INSERT INTO config_site (chave, valor) VALUES ('matriz_ip', ?)
    ON DUPLICATE KEY UPDATE valor = VALUES(valor)
");
$stmt->execute([$identidade]);

echo json_encode(['ok' => true, 'matriz_ip' => $identidade]);
