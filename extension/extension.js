import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const SOCKET_NAME = 'modular-toolbar.sock';
const SNAPSHOT_REQUEST = new TextEncoder().encode('{"type":"snapshot"}\n');
const POLL_SECONDS = 5;
const REQUEST_TIMEOUT_SECONDS = 3;
const DIGIT_LABEL_STYLE = 'font-family: monospace; min-width: 1em; width: 1em; text-align: center;';
const FIELD_STYLE = 'font-family: monospace;';
const ERROR_STYLE = 'font-family: monospace; color: #ff5f56;';
const LOW_VALUE_STYLE = 'font-family: monospace; color: #ff0000;';
const DIGIT_HEIGHT = 18;
const DIGIT_DURATION = 180;

function destroyChildren(actor) {
    let child;
    while ((child = actor.get_first_child()) !== null)
        child.destroy();
}

class OdometerField {
    constructor() {
        this.actor = new St.BoxLayout({
            y_align: Clutter.ActorAlign.CENTER,
            style: FIELD_STYLE,
        });
        this._current = null;
        this._maxLength = 0;
        this._generation = 0;
        this._error = false;
        this._warning = false;
        this._numericLayout = {
            integerWidth: 0,
            fractionWidth: 0,
            showDecimal: false,
            showSign: false,
        };
    }

    _label(text) {
        const label = new St.Label({
            text,
            y_align: Clutter.ActorAlign.CENTER,
            style: DIGIT_LABEL_STYLE,
        });
        if (this._warning || this._error)
            label.set_style(`${DIGIT_LABEL_STYLE} color: ${this._error ? '#ff5f56' : '#ff0000'};`);
        return label;
    }

    _replace(text) {
        this._generation++;
        destroyChildren(this.actor);
        const padded = this._formatText(text).padStart(this._maxLength, ' ');
        for (const character of padded)
            this.actor.add_child(this._label(character));
    }

    _number(text) {
        const value = Number(text.replaceAll(',', ''));
        return Number.isFinite(value) ? value : null;
    }

    _numericParts(text) {
        const match = /^([+-]?)(\d[\d,]*)(?:\.(\d+))?$/.exec(text.trim());
        if (!match)
            return null;
        return {
            sign: match[1],
            integer: match[2],
            fraction: match[3] || '',
            hasDecimal: Boolean(match[3]),
        };
    }

    _updateNumericLayout(parts) {
        if (!parts)
            return;
        this._numericLayout.integerWidth = Math.max(
            this._numericLayout.integerWidth,
            parts.integer.length
        );
        this._numericLayout.fractionWidth = Math.max(
            this._numericLayout.fractionWidth,
            parts.fraction.length
        );
        this._numericLayout.showDecimal ||= parts.hasDecimal;
        this._numericLayout.showSign ||= Boolean(parts.sign);
    }

    _formatText(text) {
        const parts = this._numericParts(text);
        if (!parts)
            return text.padStart(this._maxLength, ' ');

        const sign = this._numericLayout.showSign ? (parts.sign || ' ') : '';
        const integer = parts.integer.padStart(this._numericLayout.integerWidth, ' ');
        if (!this._numericLayout.showDecimal)
            return `${sign}${integer}`;

        const fraction = parts.fraction.padEnd(this._numericLayout.fractionWidth, ' ');
        return `${sign}${integer}.${fraction}`;
    }

    _animateSlot(oldCharacter, newCharacter, direction, generation) {
        if (!/^\d$/.test(oldCharacter) && !/^\d$/.test(newCharacter)) {
            this.actor.add_child(this._label(newCharacter));
            return;
        }

        if (oldCharacter === newCharacter) {
            this.actor.add_child(this._label(newCharacter));
            return;
        }

        const slot = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            clip_to_allocation: true,
            style: 'min-width: 1em; width: 1em; height: 1.2em;',
        });
        const oldLabel = this._label(oldCharacter);
        const newLabel = this._label(newCharacter);
        const offset = direction > 0 ? DIGIT_HEIGHT : -DIGIT_HEIGHT;

        newLabel.translation_y = offset;
        slot.add_child(oldLabel);
        slot.add_child(newLabel);
        this.actor.add_child(slot);

        oldLabel.ease({
            translation_y: -offset,
            duration: DIGIT_DURATION,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => {
                if (generation === this._generation && slot.get_parent())
                    oldLabel.destroy();
            },
        });
        newLabel.ease({
            translation_y: 0,
            duration: DIGIT_DURATION,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    setValue(value, animate, warning = false) {
        const text = String(value ?? '—');
        if (!this._error && this._current === text && this._warning === warning)
            return;

        const wasError = this._error;
        if (this._current !== null)
            this._replace(this._current);

        const previous = this._current;
        this._current = text;
        this._error = false;
        this._warning = warning;
        this.actor.set_style(warning ? LOW_VALUE_STYLE : FIELD_STYLE);
        this._updateNumericLayout(this._numericParts(previous));
        this._updateNumericLayout(this._numericParts(text));
        this._maxLength = Math.max(this._maxLength, text.length, previous?.length || 0);

        if (previous === null || previous === text || !animate || wasError) {
            this._replace(text);
            return;
        }

        const oldText = this._formatText(previous);
        const newText = this._formatText(text);
        this._maxLength = Math.max(this._maxLength, oldText.length, newText.length);
        const alignedOldText = oldText.padStart(this._maxLength, ' ');
        const alignedNewText = newText.padStart(this._maxLength, ' ');
        const oldNumber = this._number(previous);
        const newNumber = this._number(text);
        const direction = oldNumber !== null && newNumber !== null && newNumber < oldNumber ? -1 : 1;
        const generation = ++this._generation;

        destroyChildren(this.actor);
        for (let index = 0; index < alignedNewText.length; index++)
            this._animateSlot(alignedOldText[index], alignedNewText[index], direction, generation);
    }

    setError(marker = 'ERR') {
        if (this._error && this._current === marker)
            return;

        if (this._current !== null)
            this._replace(this._current);

        this._current = marker;
        this._error = true;
        this._warning = false;
        this._maxLength = Math.max(this._maxLength, marker.length);
        this.actor.set_style(ERROR_STYLE);
        this._replace(marker);
    }
}

// PanelMenu.Button is a GObject class. GNOME Shell 50 rejects an ordinary
// JavaScript subclass with "Tried to construct an object without a GType".
const ToolbarIndicator = GObject.registerClass(
    class ToolbarIndicator extends PanelMenu.Button {
        _init() {
            super._init(0.0, 'Modular Toolbar', false);

            this._content = new St.BoxLayout({
                y_align: Clutter.ActorAlign.CENTER,
            });
            this.add_child(this._content);
            this._viewMode = null;
            this._messageLabel = null;
            this._nameLabel = null;
            this._unitsField = null;
            this._exchangeField = null;

            this._statuses = [];
            this._index = 0;
            this._pollSource = 0;
            this._rotationSource = 0;
            this._rotationSeconds = 8;
            this._request = null;
            this._destroyed = false;
            this._lastRequestError = '';

            this._showMessage('Toolbar: starting', '#c0c0c0');

            this._requestSnapshot();
            this._pollSource = GLib.timeout_add_seconds(
                GLib.PRIORITY_DEFAULT,
                POLL_SECONDS,
                () => {
                    this._requestSnapshot();
                    return GLib.SOURCE_CONTINUE;
                }
            );
        }

        _requestSnapshot() {
            if (this._destroyed || this._request)
                return;

            const runtimeDir = GLib.getenv('XDG_RUNTIME_DIR');
            if (!runtimeDir) {
                this._setOffline('Toolbar: no runtime dir');
                return;
            }

            const path = GLib.build_filenamev([runtimeDir, SOCKET_NAME]);
            const request = {
                cancellable: new Gio.Cancellable(),
                connection: null,
                timeoutSource: 0,
                done: false,
                timedOut: false,
            };
            this._request = request;

            request.timeoutSource = GLib.timeout_add_seconds(
                GLib.PRIORITY_DEFAULT,
                REQUEST_TIMEOUT_SECONDS,
                () => {
                    if (!request.done) {
                        request.timedOut = true;
                        request.cancellable.cancel();
                        this._completeRequest(
                            request,
                            new Error(`IPC request timed out after ${REQUEST_TIMEOUT_SECONDS}s`)
                        );
                    }
                    return GLib.SOURCE_REMOVE;
                }
            );

            try {
                const client = new Gio.SocketClient();
                const address = new Gio.UnixSocketAddress({path});

                // All socket operations are asynchronous. GNOME Shell shares
                // its main loop with the panel, so connect(), write_bytes(),
                // and read_line_utf8() must not be used here.
                client.connect_async(
                    address,
                    request.cancellable,
                    (source, result) => {
                        if (request.done)
                            return;

                        try {
                            request.connection = source.connect_finish(result);
                            const output = request.connection.get_output_stream();
                            output.write_all_async(
                                SNAPSHOT_REQUEST,
                                GLib.PRIORITY_DEFAULT,
                                request.cancellable,
                                (stream, writeResult) => {
                                    if (request.done)
                                        return;

                                    try {
                                        stream.write_all_finish(writeResult);
                                        const input = new Gio.DataInputStream({
                                            base_stream: request.connection.get_input_stream(),
                                        });
                                        input.read_line_async(
                                            GLib.PRIORITY_DEFAULT,
                                            request.cancellable,
                                            (inputStream, readResult) => {
                                                if (request.done)
                                                    return;

                                                try {
                                                    const [line] = inputStream.read_line_finish_utf8(readResult);
                                                    if (!line)
                                                        throw new Error('empty backend response');

                                                    const message = JSON.parse(line);
                                                    this._applySnapshot(message);
                                                    this._completeRequest(request);
                                                } catch (error) {
                                                    this._completeRequest(request, error);
                                                }
                                            }
                                        );
                                    } catch (error) {
                                        this._completeRequest(request, error);
                                    }
                                }
                            );
                        } catch (error) {
                            this._completeRequest(request, error);
                        }
                    }
                );
            } catch (error) {
                this._completeRequest(request, error);
            }
        }

        _applySnapshot(message) {
            if (this._destroyed)
                return;

            if (!message || message.type === 'error')
                throw new Error(message?.error || 'invalid backend response');

            this._statuses = Array.isArray(message.statuses)
                ? message.statuses.slice().sort((left, right) => {
                    const leftKey = String(left.name || left.id || '');
                    const rightKey = String(right.name || right.id || '');
                    return leftKey.localeCompare(rightKey);
                })
                : [];
            if (message.settings?.rotation_interval) {
                const parsed = this._parseSeconds(message.settings.rotation_interval);
                if (parsed > 0 && parsed !== this._rotationSeconds) {
                    this._rotationSeconds = parsed;
                    this._restartRotation();
                }
            }

            this._lastRequestError = '';
            this._render();
            this._ensureRotation();
        }

        _completeRequest(request, error = null) {
            if (request.done)
                return;

            request.done = true;
            if (request.timeoutSource) {
                GLib.source_remove(request.timeoutSource);
                request.timeoutSource = 0;
            }

            try {
                request.connection?.close(null);
            } catch (closeError) {
                console.error(`[modular-toolbar] IPC close error: ${closeError}`);
            }

            if (this._request === request)
                this._request = null;

            if (!error || this._destroyed)
                return;

            // Cancellation during disable is expected. A timeout is reported
            // explicitly because otherwise its cancellation hides the cause.
            if (request.cancellable.is_cancelled() && !request.timedOut)
                return;

            const detail = error?.stack || String(error);
            if (detail !== this._lastRequestError) {
                console.error(`[modular-toolbar] IPC error: ${detail}`);
                this._lastRequestError = detail;
            }
            this._setOffline('Toolbar: backend offline');
        }

        _parseSeconds(value) {
            const match = /^(\d+(?:\.\d+)?)(s|m|h)$/.exec(value);
            if (!match)
                return 0;
            const number = Number(match[1]);
            if (match[2] === 'm')
                return Math.max(1, Math.round(number * 60));
            if (match[2] === 'h')
                return Math.max(1, Math.round(number * 3600));
            return Math.max(1, Math.round(number));
        }

        _restartRotation() {
            if (this._rotationSource) {
                GLib.source_remove(this._rotationSource);
                this._rotationSource = 0;
            }
            this._ensureRotation();
        }

        _ensureRotation() {
            if (this._destroyed)
                return;
            if (this._statuses.length <= 1) {
                if (this._rotationSource) {
                    GLib.source_remove(this._rotationSource);
                    this._rotationSource = 0;
                }
                return;
            }
            if (this._rotationSource)
                return;

            this._rotationSource = GLib.timeout_add_seconds(
                GLib.PRIORITY_DEFAULT,
                this._rotationSeconds,
                () => {
                    if (this._statuses.length <= 1) {
                        this._rotationSource = 0;
                        return GLib.SOURCE_REMOVE;
                    }
                    this._index = (this._index + 1) % this._statuses.length;
                    this._render();
                    return GLib.SOURCE_CONTINUE;
                }
            );
        }

        _clearContent() {
            destroyChildren(this._content);
            this._viewMode = null;
            this._messageLabel = null;
            this._nameLabel = null;
            this._unitsField = null;
            this._exchangeField = null;
        }

        _showMessage(text, color) {
            if (this._viewMode !== 'message') {
                this._clearContent();
                this._viewMode = 'message';
                this._messageLabel = new St.Label({
                    y_align: Clutter.ActorAlign.CENTER,
                });
                this._content.add_child(this._messageLabel);
            }
            this._messageLabel.set_style(`color: ${color};`);
            this._messageLabel.set_text(text);
        }

        _ensureStatusView() {
            if (this._viewMode === 'status')
                return;

            this._clearContent();
            this._viewMode = 'status';
            this._nameLabel = new St.Label({
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._unitsTitle = new St.Label({
                text: ' | Units: ',
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._exchangeTitle = new St.Label({
                text: ' | Exchange: ',
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._unitsField = new OdometerField();
            this._exchangeField = new OdometerField();
            this._content.add_child(this._nameLabel);
            this._content.add_child(this._unitsTitle);
            this._content.add_child(this._unitsField.actor);
            this._content.add_child(this._exchangeTitle);
            this._content.add_child(this._exchangeField.actor);
        }

        _parseDisplay(display) {
            if (typeof display !== 'string')
                return null;
            const match = /^Units:\s*(.*?)\s*\|\s*Exchange:\s*(.*?)\s*$/.exec(display);
            if (!match)
                return null;
            return {units: match[1], exchange: match[2]};
        }

        _isLowUnits(value) {
            const number = Number(String(value).replaceAll(',', ''));
            return Number.isFinite(number) && number < 1.5;
        }

        _animationsEnabled() {
            try {
                return St.Settings.get().enable_animations !== false;
            } catch (error) {
                return true;
            }
        }

        _setOffline(text) {
            if (this._destroyed)
                return;
            if (this._rotationSource) {
                GLib.source_remove(this._rotationSource);
                this._rotationSource = 0;
            }
            this._showMessage(text, '#ff5f56');
        }

        _render() {
            if (this._destroyed)
                return;

            if (!this._statuses.length) {
                this._showMessage('Toolbar: inactive', '#c0c0c0');
                return;
            }

            this._index = Math.min(this._index, this._statuses.length - 1);
            const status = this._statuses[this._index];
            const name = status.name || 'Unnamed';
            this._ensureStatusView();
            // The profile name changes immediately; only the numeric fields animate.
            this._nameLabel.set_text(name);
            if (status.error) {
                this._unitsField.setError();
                this._exchangeField.setError();
            } else {
                const values = this._parseDisplay(status.display);
                const animate = this._animationsEnabled();
                const units = values?.units || '—';
                this._unitsField.setValue(units, animate, this._isLowUnits(units));
                this._exchangeField.setValue(values?.exchange || '—', animate);
            }
        }

        destroy() {
            if (this._destroyed)
                return;
            this._destroyed = true;
            if (this._pollSource) {
                GLib.source_remove(this._pollSource);
                this._pollSource = 0;
            }
            if (this._rotationSource) {
                GLib.source_remove(this._rotationSource);
                this._rotationSource = 0;
            }
            if (this._request) {
                this._request.cancellable.cancel();
                this._completeRequest(this._request);
            }
            super.destroy();
        }
    }
);

export default class ModularToolbarExtension extends Extension {
    enable() {
        try {
            this._indicator = new ToolbarIndicator();
            this._indicator.menu.addAction('Manage Profiles…', () => {
                const settingsPath = GLib.build_filenamev([
                    GLib.get_user_data_dir(),
                    '..',
                    'bin',
                    'modular-toolbar-settings',
                ]);
                try {
                    Gio.Subprocess.new([settingsPath], Gio.SubprocessFlags.NONE);
                } catch (error) {
                    console.error(`[modular-toolbar] could not open settings: ${error?.stack || error}`);
                }
            });
            Main.panel.addToStatusArea(this.uuid, this._indicator, 1, 'right');
            console.log('[modular-toolbar] panel indicator enabled');
        } catch (error) {
            console.error(`[modular-toolbar] enable failed: ${error?.stack || error}`);
            this._indicator?.destroy();
            this._indicator = null;
            throw error;
        }
    }

    disable() {
        try {
            this._indicator?.destroy();
        } catch (error) {
            console.error(`[modular-toolbar] disable failed: ${error?.stack || error}`);
        }
        this._indicator = null;
        console.log('[modular-toolbar] panel indicator disabled');
    }
}
