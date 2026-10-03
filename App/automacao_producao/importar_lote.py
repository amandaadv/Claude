"""Importa vários arquivos .cdr mestre de uma vez, sem precisar abrir a
telinha de escolher arquivo pra cada um -- pa.do_import_from_master já
aceita um caminho direto, então isso é só um laço em volta dela com log
por arquivo (nome, quantas REFs achou, quanto tempo levou) e sem parar o
lote inteiro se um arquivo falhar.

Um .cdr só vira catálogo de verdade se tiver a legenda "REF NNN MED WxHMM"
perto de cada desenho (é assim que build_ref_index acha cada figura) --
arquivo de pedido avulso (produção de um cliente específico) não tem isso
e entra com 0 referências (não é erro, só não é catálogo).

Uso:
    python importar_lote.py caminho1.cdr caminho2.cdr ...
    python importar_lote.py --lista arquivo_com_caminhos.txt
"""
import argparse
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import pa

try:
    import win32con
    import win32gui
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False

_stop_watcher = threading.Event()


def _clicar_ok_automaticamente():
    """Muitos desses .cdr foram salvos com imagens/recursos vinculados a um
    caminho que não existe mais depois da reorganização de hoje -- o
    CorelDRAW só avisa com essa caixinha e segue sozinho usando o cache
    dele quando alguém clica OK (não cancela a importação, só precisa do
    clique). Roda em uma thread separada, o tempo todo, procurando essa
    caixinha (ou qualquer diálogo modal parecido do CorelDRAW) e clicando
    OK sozinho assim que ela aparece -- sem isso o lote inteiro trava
    esperando alguém clicar, um arquivo poucos minutos depois do outro."""
    if not _HAS_WIN32:
        print("AVISO: pywin32 indisponivel, nao consigo clicar OK sozinho nos avisos do CorelDRAW.")
        return

    while not _stop_watcher.is_set():
        time.sleep(1)
        try:
            def enum_handler(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                class_name = win32gui.GetClassName(hwnd)
                if class_name != "#32770":  # janela de dialogo padrao do Windows
                    return
                title = win32gui.GetWindowText(hwnd)
                if "corel" not in title.lower():
                    return

                def child_handler(child_hwnd, _):
                    text = win32gui.GetWindowText(child_hwnd)
                    if text.strip().upper() == "OK":
                        win32gui.SendMessage(child_hwnd, win32con.BM_CLICK, 0, 0)

                win32gui.EnumChildWindows(hwnd, child_handler, None)

            win32gui.EnumWindows(enum_handler, None)
        except Exception:
            pass


def _fechar_coreldraw():
    """do_import_from_master nunca fecha o documento que abriu -- num lote
    de dezenas de arquivos (alguns de 2GB+) isso ia acumular tudo aberto na
    memória até travar. Mais simples e confiável que fechar documento por
    documento via COM: mata o processo inteiro entre um arquivo e outro,
    a próxima chamada a connect() sobe uma instância nova, limpa."""
    subprocess.run(
        ["taskkill", "/IM", "CorelDrw.exe", "/F"],
        capture_output=True, check=False,
    )
    time.sleep(2)


def importar(paths: list[str]) -> None:
    watcher = threading.Thread(target=_clicar_ok_automaticamente, daemon=True)
    watcher.start()

    total = len(paths)
    resultados = []
    sucessos_seguidos = 0
    # Reiniciar o CorelDRAW inteiro a cada arquivo era mais seguro mas bem
    # mais lento (15-30s de reabertura por arquivo, à toa na maioria das
    # vezes) -- agora só reinicia quando algo deu errado de verdade, e a
    # cada poucos sucessos seguidos como precaução (ainda tem arquivo de
    # GBs na fila, memoria pode acumular mesmo sem erro aparente).
    REINICIAR_A_CADA = 4

    for i, path in enumerate(paths, start=1):
        print(f"\n[{i}/{total}] {path}")
        start = time.time()
        try:
            catalog_id = pa.do_import_from_master(path, None)
        except Exception as ex:
            print(f"  ERRO: {ex}")
            resultados.append((path, None, 0, "erro", time.time() - start))
            _fechar_coreldraw()
            sucessos_seguidos = 0
            continue

        elapsed = time.time() - start
        if catalog_id is None:
            # Nem chegou a abrir o CorelDRAW (duplicata pelo hash) -- nada pra fechar.
            resultados.append((path, None, 0, "nao_importado", elapsed))
            continue

        arts = pa.db.get_arts_with_sizes_by_catalog_id(catalog_id)
        resultados.append((path, catalog_id, len(arts), "ok", elapsed))
        print(f"  -> catalogo id={catalog_id}, {len(arts)} referencia(s), {elapsed:.0f}s")

        sucessos_seguidos += 1
        if sucessos_seguidos >= REINICIAR_A_CADA:
            _fechar_coreldraw()
            sucessos_seguidos = 0

    _stop_watcher.set()

    print("\n=== RESUMO ===")
    for path, catalog_id, n_refs, status, elapsed in resultados:
        nome = path.split("\\")[-1]
        print(f"{status:14s}  {n_refs:4d} ref(s)  {elapsed:6.0f}s  {nome}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--lista", help="arquivo texto com um caminho .cdr por linha")
    args = parser.parse_args()

    all_paths = list(args.paths)
    if args.lista:
        with open(args.lista, "r", encoding="utf-8-sig") as f:
            all_paths += [line.strip() for line in f if line.strip()]

    if not all_paths:
        print("Nenhum arquivo informado.")
        sys.exit(1)

    importar(all_paths)
