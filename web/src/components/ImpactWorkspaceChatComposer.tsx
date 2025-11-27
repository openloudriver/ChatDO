/**
 * Custom ChatComposer wrapper for Impact Workspace that adds context
 * from selected impacts and bullet draft to each message.
 */
import React, { useState, useRef, useEffect } from 'react';
import { useChatStore } from '../store/chat';
import type { ImpactEntry } from '../types/impact';
import { BULLET_MODES, type BulletMode } from './ActiveBulletEditor';
import RagContextTray from './RagContextTray';

interface ImpactWorkspaceChatComposerProps {
  selectedImpacts: ImpactEntry[];
  bulletMode: BulletMode;
  bulletText: string;
}

export const ImpactWorkspaceChatComposer: React.FC<ImpactWorkspaceChatComposerProps> = ({
  selectedImpacts,
  bulletMode,
  bulletText,
}) => {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  
  const {
    currentProject,
    currentConversation,
    addMessage,
    setStreaming,
    updateStreamingContent,
    clearStreaming,
    isRagTrayOpen,
    setRagTrayOpen,
    ragFileIds,
  } = useChatStore();

  // Auto-resize textarea - fixed to 2 rows
  const adjustTextareaHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = '88px'; // Fixed to 2 rows
    }
  };
  
  useEffect(() => {
    adjustTextareaHeight();
  }, [input]);

  const buildContextMessage = (): string => {
    const parts: string[] = [];
    
    const modeMeta = BULLET_MODES.find((m) => m.id === bulletMode);
    const maxCharsInfo = modeMeta?.maxChars ? ` (target: ${modeMeta.maxChars} chars)` : '';

    parts.push(`You are helping the user craft Air Force performance bullets. The user is currently working in Impact Workspace with bullet mode "${modeMeta?.label || 'Freeform'}"${maxCharsInfo}.`);
    if (bulletText.trim()) {
      parts.push(`The current draft bullet is: "${bulletText.trim()}"`);
    } else {
      parts.push("The current draft bullet is empty.");
    }
    parts.push("Always keep suggestions within the character limit for the selected mode.");
    
    // Add selected impacts
    if (selectedImpacts.length > 0) {
      parts.push("\n=== SELECTED IMPACTS ===");
      selectedImpacts.forEach((impact, idx) => {
        parts.push(`\nImpact ${idx + 1}:`);
        if (impact.title) parts.push(`Title: ${impact.title}`);
        if (impact.date) parts.push(`Date: ${new Date(impact.date).toLocaleDateString()}`);
        if (impact.context) parts.push(`Context: ${impact.context}`);
        if (impact.actions) parts.push(`Actions: ${impact.actions}`);
        if (impact.impact) parts.push(`Impact: ${impact.impact}`);
        if (impact.metrics) parts.push(`Metrics: ${impact.metrics}`);
        if (impact.notes) parts.push(`Notes: ${impact.notes}`);
        if (impact.tags && impact.tags.length > 0) {
          parts.push(`Tags: ${impact.tags.join(", ")}`);
        }
      });
    }
    
    // Add RAG context files info
    if (ragFileIds.length > 0) {
      parts.push(`\n=== CONTEXT FILES ===`);
      parts.push(`${ragFileIds.length} context file(s) uploaded for this conversation. Use these files as reference when drafting bullets.`);
    }
    
    parts.push("\nUse the selected impacts and context files to help draft content for the bullet. Respect character limits when provided. Reference context files when you need more detail.");
    
    return parts.join("\n");
  };

  const handleSend = async () => {
    if (!input.trim() || !currentProject || !currentConversation) return;

    const userMessage = input.trim();
    const contextMessage = buildContextMessage();
    
    // Prepend context to user message
    const messageWithContext = contextMessage 
      ? `${contextMessage}\n\n=== USER REQUEST ===\n${userMessage}`
      : userMessage;

    // Add user message to chat
    addMessage({
      role: 'user',
      content: userMessage,
    });

    // Clear input
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = '88px';
    }

    try {
      // Use WebSocket for streaming
      const ws = new WebSocket('ws://localhost:8000/api/chat/stream');
      let streamedContent = '';
      
      ws.onopen = () => {
        setStreaming(true);
        const payload = {
          project_id: currentProject.id,
          conversation_id: currentConversation.id,
          target_name: currentConversation.targetName,
          message: messageWithContext, // Send message with context
          force_search: false,
          context: {
            origin: 'impact_workspace',
            selectedImpactIds: selectedImpacts.map(i => i.id),
            bulletDraft: bulletText,
            bulletMode,
            ragFileIds,
          }
        };
        ws.send(JSON.stringify(payload));
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'chunk') {
            streamedContent += data.content;
            updateStreamingContent(streamedContent);
          } else if (data.type === 'done') {
            addMessage({
              role: 'assistant',
              content: streamedContent,
            });
            clearStreaming();
            ws.close();
          } else if (data.type === 'error') {
            addMessage({
              role: 'assistant',
              content: `Error: ${data.content}`,
            });
            clearStreaming();
            ws.close();
          }
        } catch (e) {
          console.error('Error parsing WebSocket message:', e);
        }
      };
      
      ws.onerror = () => {
        clearStreaming();
        ws.close();
        // Fallback to REST API if WebSocket fails
        addMessage({
          role: 'assistant',
          content: 'Connection error. Please try again.',
        });
      };
      
    } catch (error) {
      console.error('Error sending message:', error);
      addMessage({
        role: 'assistant',
        content: 'Failed to send message. Please try again.',
      });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      <div className="px-4 py-3 border-t border-slate-700 bg-[#343541]">
        <div className="relative flex items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              adjustTextareaHeight(); // This will now enforce min/max height
            }}
            onKeyDown={handleKeyDown}
            placeholder="Message ChatDO about your impacts and template..."
            className="w-full p-3 pl-3 pr-24 bg-[#40414f] text-white rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-[#19c37d] overflow-y-auto"
            style={{ minHeight: '88px', maxHeight: '300px', height: '88px' }} // Fixed to 2 rows
          />
          <div className="absolute right-2 bottom-2 flex items-center gap-1">
            {/* RAG Tray Toggle Button (Lightbulb) */}
            <button
              onClick={() => setRagTrayOpen(!isRagTrayOpen)}
              className={`p-2 rounded transition-colors ${
                isRagTrayOpen
                  ? 'text-[#19c37d] bg-[#19c37d]/20'
                  : 'text-[#8e8ea0] hover:text-white hover:bg-[#565869]'
              }`}
              title="RAG context tray (upload reference files)"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </button>
            {/* Send button */}
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="flex-shrink-0 w-8 h-8 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-400 text-white flex items-center justify-center transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        </div>
        {(selectedImpacts.length > 0 || bulletText.trim() || ragFileIds.length > 0) && (
          <div className="mt-2 text-xs text-slate-400">
            Context: {selectedImpacts.length} impact{selectedImpacts.length !== 1 ? "s" : ""} selected
            {bulletText.trim() && ` • Bullet: ${bulletMode} (${bulletText.length}${BULLET_MODES.find(m => m.id === bulletMode)?.maxChars ? ` / ${BULLET_MODES.find(m => m.id === bulletMode)?.maxChars}` : ''} chars)`}
            {ragFileIds.length > 0 && ` • ${ragFileIds.length} context file${ragFileIds.length !== 1 ? 's' : ''}`}
          </div>
        )}
      </div>
      {/* RAG Context Tray */}
      <RagContextTray 
        isOpen={isRagTrayOpen} 
        onClose={() => setRagTrayOpen(false)}
      />
    </>
  );
};
