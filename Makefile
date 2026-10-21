.PHONY: build test install uninstall
BINARY=bin/modular-toolbar
SETTINGS_APP=settings/modular-toolbar-settings.py
DESKTOP_FILE=settings/com.example.ModularToolbar.desktop
build:
	mkdir -p bin
	go build -buildvcs=false -o $(BINARY) ./cmd/toolbar
test:
	go test ./...
	/usr/bin/python3 -m unittest discover -s settings -p 'test_*.py'
install: build
	install -Dm755 $(BINARY) $(HOME)/.local/bin/modular-toolbar
	rm -rf $(HOME)/.local/share/gnome-shell/extensions/modular-toolbar@example.com
	install -d $(HOME)/.local/share/gnome-shell/extensions/modular-toolbar@example.com
	cp -a extension/. $(HOME)/.local/share/gnome-shell/extensions/modular-toolbar@example.com/
	grep -q '"50"' $(HOME)/.local/share/gnome-shell/extensions/modular-toolbar@example.com/metadata.json
	install -Dm644 systemd/modular-toolbar.service $(HOME)/.config/systemd/user/modular-toolbar.service
	install -Dm755 $(SETTINGS_APP) $(HOME)/.local/bin/modular-toolbar-settings
	install -Dm644 $(DESKTOP_FILE) $(HOME)/.local/share/applications/com.example.ModularToolbar.desktop
	sed -i 's|@HOME@|$(HOME)|g' $(HOME)/.local/share/applications/com.example.ModularToolbar.desktop
	systemctl --user daemon-reload
	systemctl --user enable --now modular-toolbar.service
uninstall:
	-systemctl --user disable --now modular-toolbar.service
	rm -rf $(HOME)/.local/share/gnome-shell/extensions/modular-toolbar@example.com
	rm -f $(HOME)/.local/bin/modular-toolbar $(HOME)/.local/bin/modular-toolbar-settings $(HOME)/.local/share/applications/com.example.ModularToolbar.desktop $(HOME)/.config/systemd/user/modular-toolbar.service
	systemctl --user daemon-reload
