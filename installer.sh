#!/bin/bash
#/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/cbusillo/ebay_pictures_tool/main/installer.sh)"

handle_error() {
    echo "Error: $1"
    exit 1
}

get_brew_path() {
    if command -v /usr/local/bin/brew &> /dev/null; then
        echo "/usr/local/bin/brew"
    elif command -v /opt/homebrew/bin/brew &> /dev/null; then
        echo "/opt/homebrew/bin/brew"
    else
        echo ""
    fi
}

update_zshrc() {
    ZSHRC_PATH="$HOME/.zshrc"
    # Checking if the path exists in .zshrc
    if ! grep -q "export PATH=\"$1:\$PATH\"" "$ZSHRC_PATH"; then
        echo "export PATH=\"$1:\$PATH\"" >> "$ZSHRC_PATH"
        echo "Updated .zshrc with new PATH"
    else
        echo ".zshrc already contains the PATH"
    fi
}

BREW_PATH=$(get_brew_path)
if [ -z "$BREW_PATH" ]; then
    echo "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || handle_error "Failed to install Homebrew"
    BREW_PATH=$(get_brew_path)
fi

export PATH="$BREW_PATH:$PATH"
update_zshrc "$BREW_PATH"

$BREW_PATH install python@3.11 zbar || handle_error "Failed to install python@3.11 or zbar"
$BREW_PATH upgrade python@3.11 zbar || handle_error "Failed to upgrade python@3.11 or zbar"

PIP_PATH="${BREW_PATH%/brew}/bin/pip3.11"

$PIP_PATH install -U ebay_pictures_tool || handle_error "Failed to install ebay_pictures_tool"