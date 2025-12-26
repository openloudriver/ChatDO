#!/bin/bash
# Helper script to run Facts acceptance tests with auto-generated test IDs

set -e

# Generate test project UUID and thread ID
PROJECT_UUID=$(python3 -c "import uuid; print(str(uuid.uuid4()))")
THREAD_ID="test-facts-$(date +%s)"

echo "=========================================="
echo "Facts Acceptance Test Runner"
echo "=========================================="
echo "Test Project UUID: $PROJECT_UUID"
echo "Test Thread ID: $THREAD_ID"
echo ""
echo "Prerequisites check:"
echo "  - Checking Ollama..."

# Check if Ollama is running
if curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    echo "  ✅ Ollama is running"
    
    # Check if qwen2.5:7b-instruct model is available
    if curl -s http://127.0.0.1:11434/api/tags | grep -q "qwen2.5:7b-instruct"; then
        echo "  ✅ qwen2.5:7b-instruct model is available"
    else
        echo "  ⚠️  qwen2.5:7b-instruct model not found. Please pull it with:"
        echo "     ollama pull qwen2.5:7b-instruct"
        exit 1
    fi
else
    echo "  ❌ Ollama is not running. Please start Ollama first."
    exit 1
fi

echo ""
echo "Running acceptance tests..."
echo ""

# Run the test script
python3 test_facts_acceptance.py \
    --project-uuid "$PROJECT_UUID" \
    --thread-id "$THREAD_ID" \
    --test all

echo ""
echo "=========================================="
echo "Tests completed!"
echo "=========================================="

