# Render with: vhs vhs/solab.tape   (needs SOLARI_API_KEY in ../.env; spends a few cents)
Output docs/solab.gif
Output ../.frames_lab/
Set Shell zsh
Set FontSize 15
Set Width 1180
Set Height 720
Set Padding 24
Set Theme { "name": "solari", "background": "#080a0e", "foreground": "#e7e7e2", "cursor": "#f5b301", "black": "#080a0e", "red": "#ff5c5c", "green": "#9bd89a", "yellow": "#f5c66a", "blue": "#939599", "magenta": "#f5b301", "cyan": "#819895", "white": "#e7e7e2", "brightBlack": "#474747", "brightRed": "#ff5c5c", "brightGreen": "#9bd89a", "brightYellow": "#f5c66a", "brightBlue": "#939599", "brightMagenta": "#f5b301", "brightCyan": "#819895", "brightWhite": "#ffffff" }
Set TypingSpeed 40ms
Set PlaybackSpeed 1.0

Hide
Type "set -a; source ../.env; set +a; export PATH=$PWD/.venv/bin:$PATH; clear"
Enter
Sleep 500ms
Show

Type "solab doctor"
Sleep 300ms
Enter
Sleep 9s

Type "clear"
Enter
Type "solab --plan starter bench --n 5"
Sleep 300ms
Enter
Sleep 16s

Type "clear"
Enter
Type "solab --plan starter proxy --countries gb --tiers residential,static"
Sleep 300ms
Enter
Sleep 30s

Type "clear"
Enter
Type "solab --plan starter isolation --tries 4"
Sleep 300ms
Enter
Sleep 30s
Sleep 3s
