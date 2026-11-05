# Extensão TWB: a sessão do jogo sem copiar cookie

Chrome, Edge ou outro navegador Chromium. Instala uma vez:

1. Abra `chrome://extensions` (no Edge, `edge://extensions`).
2. Ligue o **Modo do desenvolvedor**.
3. **Carregar sem compactação** → escolha esta pasta (`browser_extension`).

Depois, sempre:

1. Abra o painel do bot (`cd webmanager` e `python server.py`).
2. Entre no jogo no navegador, no mundo que está no `config.json`.

A extensão manda a sessão para o painel sozinha a cada login, e o painel a
testa antes de gravar. O ícone mostra **OK** quando o painel aceitou. O bot
esperando por sessão começa em até 15 s; o bot rodando troca para a sessão
nova no começo do ciclo seguinte. Se o painel estava fechado na hora do login,
a extensão tenta de novo a cada minuto. O botão **Enviar sessão agora** no
ícone faz o mesmo na mão.

Os cookies só vão para `127.0.0.1`. O painel só aceita esta extensão (id
fixo pela `key` do `manifest.json`), e só de `127.0.0.1`/`localhost`.

Sem a extensão continua valendo o caminho antigo: colar o cabeçalho `cookie:`
inteiro em `cache/cookies.txt`.
