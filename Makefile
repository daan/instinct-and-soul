PORT ?=

.PHONY: help repl reset ls

help:
	@echo "instinct-and-soul — common dev commands"
	@echo ""
	@echo "Console scripts (after 'uv sync'):"
	@echo "  spine creatures/<name> [--resume]"
	@echo "  tune  creatures/<name>"
	@echo "  flash creatures/<name> [--port /dev/cu.usbmodem...]"
	@echo ""
	@echo "Device shell (mpremote):"
	@echo "  make repl  PORT=/dev/cu.usbmodem...     # interactive REPL"
	@echo "  make reset PORT=/dev/cu.usbmodem...     # soft-reset board"
	@echo "  make ls    PORT=/dev/cu.usbmodem...     # list files on board"

repl:
	@test -n "$(PORT)" || (echo "usage: make repl PORT=/dev/..."; exit 1)
	mpremote connect $(PORT) repl

reset:
	@test -n "$(PORT)" || (echo "usage: make reset PORT=/dev/..."; exit 1)
	mpremote connect $(PORT) reset

ls:
	@test -n "$(PORT)" || (echo "usage: make ls PORT=/dev/..."; exit 1)
	mpremote connect $(PORT) ls
