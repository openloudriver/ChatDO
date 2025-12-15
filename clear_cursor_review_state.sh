#!/bin/bash
# Script to clear Cursor Review panel state
# This attempts to clear the "46 Files" review panel that's stuck showing

WORKSPACE_STORAGE="$HOME/Library/Application Support/Cursor/User/workspaceStorage"
GLOBAL_STORAGE="$HOME/Library/Application Support/Cursor/User/globalStorage"

echo "Clearing Cursor Review panel state..."

# Find ChatDO workspace directories
for dir in "$WORKSPACE_STORAGE"/*/; do
    if [ -f "$dir/workspace.json" ]; then
        folder=$(cat "$dir/workspace.json" 2>/dev/null | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('folder', ''))" 2>/dev/null)
        if echo "$folder" | grep -qi "chatdo"; then
            workspace_id=$(basename "$dir")
            echo "Found ChatDO workspace: $workspace_id"
            
            # Clear SCM view state (Source Control panel)
            if [ -f "$dir/state.vscdb" ]; then
                echo "  Clearing workbench.scm.views.state..."
                sqlite3 "$dir/state.vscdb" "DELETE FROM ItemTable WHERE key='workbench.scm.views.state';" 2>/dev/null
                echo "  Cleared workspace SCM state"
            fi
            
            # Clear any review-related keys in workspace state
            sqlite3 "$dir/state.vscdb" "DELETE FROM ItemTable WHERE key LIKE '%review%' OR key LIKE '%Review%' OR key LIKE '%diff%' OR key LIKE '%Diff%';" 2>/dev/null
            
            # Clear SCM (Source Control) related state keys that might be keeping Review panel open
            sqlite3 "$dir/state.vscdb" "DELETE FROM ItemTable WHERE key LIKE 'scm:%' OR key LIKE 'scm.%' OR key LIKE '%scm%' OR key LIKE 'workbench.scm%' OR key LIKE 'memento/workbench.editors.textDiffEditor%';" 2>/dev/null
            
            # Clear workspace activity and panel state (might contain Review panel state)
            sqlite3 "$dir/state.vscdb" "DELETE FROM ItemTable WHERE key LIKE 'workbench.activity%' OR key LIKE 'workbench.panel%' OR key LIKE 'workbench.view%';" 2>/dev/null
            echo "  Cleared workspace activity/panel state and SCM state"
        fi
    fi
done

# Clear codeBlockDiff entries from global storage (these might be the diff views)
echo "Clearing codeBlockDiff entries from global storage..."
sqlite3 "$GLOBAL_STORAGE/state.vscdb" "DELETE FROM cursorDiskKV WHERE key LIKE 'codeBlockDiff:%';" 2>/dev/null
echo "Cleared codeBlockDiff entries"

# Also try clearing any review-related keys in global storage
sqlite3 "$GLOBAL_STORAGE/state.vscdb" "DELETE FROM cursorDiskKV WHERE key LIKE '%review%' OR key LIKE '%Review%';" 2>/dev/null

echo ""
echo "Done! Please restart Cursor for changes to take effect."
echo "If the Review panel is still showing, try:"
echo "  1. Close the Review panel/tab in Cursor UI"
echo "  2. Restart Cursor completely"
echo "  3. If still stuck, the state might be in memory - close all Cursor windows and restart"

