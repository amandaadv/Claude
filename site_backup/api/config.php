<?php
// Credenciais reais ficam em config.local.php (NUNCA vai pro git -- veja .gitignore).
// Esse arquivo só define os valores padrão/placeholder e carrega o local se existir.

$DB_HOST = 'localhost';
$DB_NAME = 'TROQUE_AQUI';
$DB_USER = 'TROQUE_AQUI';
$DB_PASS = 'TROQUE_AQUI';

// Token secreto que o programa do computador usa pra falar com essas APIs
// (ver pedidos, publicar catálogo). Gere uma string aleatória grande e usa
// a mesma no arquivo local do programa Python.
$API_SECRET = 'TROQUE_AQUI';

// IP da máquina "matriz" -- só o que essa máquina publica aparece pro
// cliente final em catalogo.php. Vazio/TROQUE_AQUI = mostra tudo (sem
// restrição), pra nunca esvaziar a vitrine só por falta de configurar isso.
$MATRIZ_IP = 'TROQUE_AQUI';

$local_config = __DIR__ . '/config.local.php';
if (file_exists($local_config)) {
    require $local_config;
}

// CORS: o subdomínio pedido.babyluzconfeccao.com.br roda a mesma vitrine
// (com o diferencial da lista de REFs em lote) só que com pasta própria no
// servidor -- pro navegador isso é uma origem diferente do site principal,
// então sem isso o fetch() de lá pra essa API falhava silenciosamente.
$ALLOWED_ORIGINS = [
    'https://babyluzconfeccao.com.br',
    'https://www.babyluzconfeccao.com.br',
    'https://pedido.babyluzconfeccao.com.br',
];
$origin = $_SERVER['HTTP_ORIGIN'] ?? '';
if (in_array($origin, $ALLOWED_ORIGINS, true)) {
    header("Access-Control-Allow-Origin: $origin");
    header('Access-Control-Allow-Headers: Content-Type, X-Api-Secret, X-Machine-Id');
    header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
}
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    http_response_code(204);
    exit;
}

function get_pdo(): PDO {
    global $DB_HOST, $DB_NAME, $DB_USER, $DB_PASS;
    $dsn = "mysql:host=$DB_HOST;dbname=$DB_NAME;charset=utf8mb4";
    return new PDO($dsn, $DB_USER, $DB_PASS, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
}

function require_api_secret(): void {
    global $API_SECRET;
    $headers = getallheaders();
    $given = $headers['X-Api-Secret'] ?? ($headers['x-api-secret'] ?? '');
    if (!hash_equals($API_SECRET, $given)) {
        http_response_code(401);
        echo json_encode(['erro' => 'não autorizado']);
        exit;
    }
}

function json_body(): array {
    $raw = file_get_contents('php://input');
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

// Sessão de login do representante (painel.html) -- cookie próprio,
// separado de qualquer outra coisa no domínio; httponly pra não dar pra ler
// via JS (mitiga XSS) e secure porque o site só roda em HTTPS.
function iniciar_sessao_representante(): void {
    if (session_status() === PHP_SESSION_NONE) {
        session_set_cookie_params([
            'lifetime' => 0,
            'path' => '/',
            'secure' => true,
            'httponly' => true,
            'samesite' => 'Lax',
        ]);
        session_start();
    }
}

// Identifies WHICH computer is calling -- used to scope a machine's own
// catalogs (see catalogo.php/meus_catalogos.php/excluir_*.php/definir_matriz.php).
// Used to be $_SERVER['REMOTE_ADDR'] alone, which broke in practice: the shop's
// own machine's outbound connection flips between an IPv4 and an IPv6 address
// depending on the network at the moment (confirmed live -- the same machine,
// seconds apart, showed up as 179.209.45.34 once and 2804:14c:90:...:a50a the
// next), so a catalog published right when that flip happened silently stopped
// matching whatever IP was already on record as the matriz. X-Machine-Id is a
// random id the app generates once and keeps forever in a local file
// (paths.py's MACHINE_ID_FILE_PATH) -- it never changes just because the
// network did. Falls back to the old IP-based behavior only if an older/
// not-yet-updated client doesn't send the header at all.
function get_caller_identity(): string {
    $headers = getallheaders();
    $machine_id = $headers['X-Machine-Id'] ?? ($headers['x-machine-id'] ?? '');
    if ($machine_id !== '') {
        return $machine_id;
    }
    return (string)($_SERVER['REMOTE_ADDR'] ?? '');
}
