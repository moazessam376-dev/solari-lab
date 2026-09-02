# Render with: vhs vhs/solab.tape   (needs SOLARI_API_KEY in ../.env; spends a few cents)
Output docs/solab.gif
Set Shell zsh
Set FontSize 15
Set Width 1180
Set Height 720
Set Padding 24
Set Theme { "name": "solari", "background": "#0b0b0c", "foreground": "#e8e6e1", "cursor": "#ff7a1a", "black": "#0b0b0c", "red": "#ff4d4f", "green": "#38d16a", "yellow": "#f5c542", "blue": "#8a8a8a", "magenta": "#ff7a1a", "cyan": "#8a8a8a", "white": "#e8e6e1", "brightBlack": "#4a4a4a", "brightRed": "#ff4d4f", "brightGreen": "#38d16a", "brightYellow": "#f5c542", "brightBlue": "#8a8a8a", "brightMagenta": "#ff7a1a", "brightCyan": "#8a8a8a", "brightWhite": "#ffffff" }
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
