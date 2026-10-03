<?php
// Protegido (X-Api-Secret): edita nome, usuario, ativo e regiao de um
// representante existente. Se "senha" vier no body (não vazio) a senha é
// redefinida; caso contrário a senha atual é mantida.
require __DIR__ . '/config.php';
header('Content-Type: application/json; charset=utf-8');
require_api_secret();

$body    = json_body();
$id      = (int)($body['id']      ?? 0);
$nome    = trim($body['nome']     ?? '');
$usuario = trim($body['usuario']  ?? '');
$ativo   = isset($body['ativo']) ? (int)(bool)$body['ativo'] : null;
$regiao  = trim($body['regiao']   ?? '');
$senha   = $body['senha'] ?? '';

if (!$id || !$nome || !$usuario || $ativo === null) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'erro' => 'id, nome, usuario e ativo são obrigatórios']);
    exit;
}
if ($senha && strlen($senha) < 4) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'erro' => 'senha muito curta (mínimo 4 caracteres)']);
    exit;
}

$pdo = get_pdo();
foreach ([
    "ALTER TABLE representantes ADD COLUMN regiao VARCHAR(100) NULL",
] as $sql) {
    try { $pdo->exec($sql); } catch (Exception $e) { /* coluna ja existe */ }
}

$check = $pdo->prepare("SELECT id FROM representantes WHERE usuario = ? AND id != ?");
$check->execute([$usuario, $id]);
if ($check->fetch()) {
    http_response_code(409);
    echo json_encode(['ok' => false, 'erro' => 'usuário já existe em outro representante']);
    exit;
}

if ($senha) {
    $hash = password_hash($senha, PASSWORD_DEFAULT);
    $stmt = $pdo->prepare("
        UPDATE representantes SET nome = ?, usuario = ?, ativo = ?, regiao = ?, senha_hash = ? WHERE id = ?
    ");
    $stmt->execute([$nome, $usuario, $ativo, $regiao, $hash, $id]);
} else {
    $stmt = $pdo->prepare("
        UPDATE representantes SET nome = ?, usuario = ?, ativo = ?, regiao = ? WHERE id = ?
    ");
    $stmt->execute([$nome, $usuario, $ativo, $regiao, $id]);
}

echo json_encode(['ok' => true]);
