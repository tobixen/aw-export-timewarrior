.PHONY: help install install-dev install-all test lint format clean uninstall install-service uninstall-service enable-service disable-service

help:
	@echo "Available targets:"
	@echo "  install-all       - Complete setup (install + enable service)"
	@echo "  install           - Install the package using pip"
	@echo "  install-dev       - Install with development dependencies"
	@echo "  test              - Run tests"
	@echo "  lint              - Run linting (ruff check)"
	@echo "  format            - Format code (ruff format)"
	@echo "  clean             - Remove build artifacts and cache"
	@echo "  install-service   - Install systemd user service"
	@echo "  uninstall-service - Uninstall systemd user service"
	@echo "  enable-service    - Install and enable the service"
	@echo "  disable-service   - Disable and stop the service"
	@echo "  uninstall         - Uninstall the package"

install:
	pip install --user .
	@echo ""
	@echo "✓ aw-export-timewarrior installed successfully!"
	@echo ""
	@echo "Make sure ~/.local/bin is in your PATH."
	@echo ""
	@echo "Next steps:"
	@echo "  1. Configure rules in ~/.config/aw-export-timewarrior/config.toml"
	@echo "     See README.md for configuration examples"
	@echo ""
	@echo "  2. Run as systemd service (recommended for continuous sync):"
	@echo "     make enable-service"
	@echo ""
	@echo "  3. Or run manually:"
	@echo "     aw-export-timewarrior sync          # Continuous sync mode"
	@echo "     aw-export-timewarrior report        # View activity report"
	@echo "     aw-export-timewarrior diff --day    # Compare with TimeWarrior"
	@echo ""

install-dev:
	pip install -e ".[dev]"

install-all: install enable-service
	@echo ""
	@echo "✓ Installation complete!"
	@echo "  The exporter is now installed and running as a systemd service."
	@echo ""
	@echo "Check status with: systemctl --user status aw-export-timewarrior"
	@echo "View logs with:    journalctl --user -u aw-export-timewarrior -f"

test:
	pytest tests/ -v

lint:
	ruff check .

format:
	ruff format .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf dist/ build/

install-service:
	@echo "Installing systemd user service..."
	mkdir -p ~/.config/systemd/user
	cp misc/aw-export-timewarrior.service ~/.config/systemd/user/
	systemctl --user daemon-reload
	@echo "Service installed. Use 'make enable-service' to enable and start it."

uninstall-service:
	@echo "Uninstalling systemd user service..."
	systemctl --user stop aw-export-timewarrior 2>/dev/null || true
	systemctl --user disable aw-export-timewarrior 2>/dev/null || true
	rm -f ~/.config/systemd/user/aw-export-timewarrior.service
	systemctl --user daemon-reload
	@echo "Service uninstalled."

enable-service: install-service
	@echo "Enabling and starting service..."
	systemctl --user enable aw-export-timewarrior
	systemctl --user start aw-export-timewarrior
	@echo "Service status:"
	@systemctl --user status aw-export-timewarrior --no-pager

disable-service:
	@echo "Disabling and stopping service..."
	systemctl --user stop aw-export-timewarrior
	systemctl --user disable aw-export-timewarrior
	@echo "Service disabled."

uninstall:
	pip uninstall -y aw-export-timewarrior 2>/dev/null || true
	@echo "Package uninstalled."
