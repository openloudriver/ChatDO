/**
 * Custom ChatComposer wrapper for Impact Workspace that adds context
 * from selected impacts and bullet draft to each message.
 */
import React, { useState, useRef, useEffect } from 'react';
import { useChatStore } from '../store/chat';
import type { ImpactEntry } from '../types/impact';
import { BULLET_MODES, type BulletMode } from './ActiveBulletEditor';
import RagContextTray from './RagContextTray';
import { useTheme } from '../contexts/ThemeContext';

interface ImpactWorkspaceChatComposerProps {
  selectedImpacts: ImpactEntry[];
  bulletMode: BulletMode;
  bulletText: string;
  ragFileIds?: string[];
  onRagFileIdsChange?: (ragFileIds: string[]) => void;
  onMessageSent?: (message: any) => void;
  onToggleRagTray?: () => void;
  isRagTrayOpen?: boolean;
}

export const ImpactWorkspaceChatComposer: React.FC<ImpactWorkspaceChatComposerProps> = ({
  selectedImpacts,
  bulletMode,
  bulletText,
  ragFileIds: propRagFileIds,
  onRagFileIdsChange,
  onMessageSent,
  onToggleRagTray,
  isRagTrayOpen: propIsRagTrayOpen,
}) => {
  const { theme } = useTheme();
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  
  const {
    currentProject,
    currentConversation,
    addMessage,
    setStreaming,
    updateStreamingContent,
    clearStreaming,
    isRagTrayOpen: storeIsRagTrayOpen,
    setRagTrayOpen,
    ragFileIds: storeRagFileIds,
  } = useChatStore();
  
  // Use prop ragFileIds if provided, otherwise fall back to store
  const ragFileIds = propRagFileIds ?? storeRagFileIds;
  // Use prop isRagTrayOpen if provided, otherwise fall back to store
  const isRagTrayOpen = propIsRagTrayOpen ?? storeIsRagTrayOpen;
  
  const handleToggleRagTray = () => {
    if (onToggleRagTray) {
      onToggleRagTray();
    } else {
      setRagTrayOpen(!isRagTrayOpen);
    }
  };

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
    const maxChars = modeMeta?.maxChars ?? 215;
    const maxCharsInfo = modeMeta?.maxChars ? ` (target: ${modeMeta.maxChars} chars)` : '';

    // Determine if we have an activeBullet to iterate on
    const primaryImpact = selectedImpacts[0]; // Use first selected impact
    const hasActiveBullet = !!(primaryImpact?.activeBullet?.trim());
    const baseText = hasActiveBullet 
      ? primaryImpact!.activeBullet!.trim()
      : (primaryImpact ? `${primaryImpact.actions}${primaryImpact.impact ? ` - ${primaryImpact.impact}` : ''}${primaryImpact.metrics ? ` - ${primaryImpact.metrics}` : ''}`.trim() : '');

    if (hasActiveBullet) {
      // Iterating on existing bullet
      parts.push(`You are iterating on an existing Air Force performance bullet.`);
      parts.push(`\nCurrent bullet:`);
      parts.push(`"${baseText}"`);
      parts.push(`\nReturn exactly three improved versions of this bullet, each <= ${maxChars} characters, preserving the same facts and metrics.`);
      parts.push(`Focus on clarity, impact, and staying within the ${maxChars}-character limit.`);
    } else {
      // Drafting new bullet from impact
      parts.push(`You are drafting a new Air Force performance bullet from this impact description.`);
      parts.push(`\nImpact description:`);
      if (primaryImpact) {
        if (primaryImpact.title) parts.push(`Title: ${primaryImpact.title}`);
        if (primaryImpact.date) parts.push(`Date: ${new Date(primaryImpact.date).toLocaleDateString()}`);
        if (primaryImpact.context) parts.push(`Context: ${primaryImpact.context}`);
        if (primaryImpact.actions) parts.push(`Actions: ${primaryImpact.actions}`);
        if (primaryImpact.impact) parts.push(`Impact: ${primaryImpact.impact}`);
        if (primaryImpact.metrics) parts.push(`Metrics: ${primaryImpact.metrics}`);
        if (primaryImpact.notes) parts.push(`Notes: ${primaryImpact.notes}`);
        if (primaryImpact.tags && primaryImpact.tags.length > 0) {
          parts.push(`Tags: ${primaryImpact.tags.join(", ")}`);
        }
      }
      parts.push(`\nReturn exactly three bullets, each <= ${maxChars} characters.`);
    }
    
    parts.push(`\nBullet mode: "${modeMeta?.label || 'Freeform'}"${maxCharsInfo}.`);
    parts.push("Always keep suggestions within the character limit for the selected mode.");
    
    // For Award (215) bullets, ensure they start with "- " prefix
    if (bulletMode === '1206_2LINE') {
      parts.push(`\nIMPORTANT: Each bullet option MUST start with "- " (dash followed by space). For example: "- Led DAF CLOUDworks..."`);
      parts.push(`The "- " prefix is part of the bullet format and should be included in the character count.`);
    }
    
    // Add additional selected impacts if there are multiple
    if (selectedImpacts.length > 1) {
      parts.push("\n=== ADDITIONAL SELECTED IMPACTS ===");
      selectedImpacts.slice(1).forEach((impact, idx) => {
        parts.push(`\nImpact ${idx + 2}:`);
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

    // Create user message object
    const userMessageObj = {
      id: `msg-${Date.now()}-${Math.random()}`,
      role: 'user' as const,
      content: userMessage,
      timestamp: new Date(),
    };

    // Add user message - use onMessageSent if provided (impact-scoped), otherwise use store
    if (onMessageSent) {
      onMessageSent(userMessageObj);
    } else {
      addMessage(userMessageObj);
    }

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
            if (onMessageSent) {
              // For impact-scoped, we'll update the last message when done
              // For now, just update streaming content
              updateStreamingContent(streamedContent);
            } else {
              updateStreamingContent(streamedContent);
            }
          } else if (data.type === 'done') {
            const assistantMessageObj = {
              id: `msg-${Date.now()}-${Math.random()}`,
              role: 'assistant' as const,
              content: streamedContent,
              timestamp: new Date(),
            };
            if (onMessageSent) {
              onMessageSent(assistantMessageObj);
            } else {
              addMessage(assistantMessageObj);
            }
            clearStreaming();
            ws.close();
          } else if (data.type === 'error') {
            const errorMessageObj = {
              id: `msg-${Date.now()}-${Math.random()}`,
              role: 'assistant' as const,
              content: `Error: ${data.content}`,
              timestamp: new Date(),
            };
            if (onMessageSent) {
              onMessageSent(errorMessageObj);
            } else {
              addMessage(errorMessageObj);
            }
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
      <div className="px-4 py-3 border-t border-[var(--border-color)] bg-[var(--bg-primary)] transition-colors">
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
            className="w-full p-3 pl-3 pr-24 bg-[var(--bg-tertiary)] text-[var(--text-primary)] rounded-lg resize-none focus:outline-none overflow-y-auto transition-colors"
            style={{ 
              minHeight: '88px', 
              maxHeight: '300px', 
              height: '88px',
              '--tw-ring-color': 'var(--user-bubble-bg)'
            } as React.CSSProperties & { '--tw-ring-color': string }}
            onFocus={(e) => {
              e.currentTarget.style.boxShadow = '0 0 0 2px var(--user-bubble-bg)';
            }}
            onBlur={(e) => {
              e.currentTarget.style.boxShadow = '';
            }}
          />
          <div className="absolute right-2 bottom-2 flex items-center gap-1">
            {/* RAG Tray Toggle Button (Lightbulb) */}
            <button
              onClick={handleToggleRagTray}
              className={`p-2 rounded transition-colors relative ${
                isRagTrayOpen
                  ? ''
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--border-color)]'
              }`}
              style={isRagTrayOpen ? {
                color: 'var(--user-bubble-bg)'
              } : undefined}
              title="RAG context tray (upload reference files)"
            >
              {isRagTrayOpen && (
                <div 
                  className="absolute inset-0 rounded"
                  style={{
                    backgroundColor: 'var(--user-bubble-bg)',
                    opacity: 0.2
                  }}
                />
              )}
              <svg className="w-5 h-5 relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </button>
            {/* Send button */}
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="flex-shrink-0 w-8 h-8 rounded-lg disabled:bg-slate-700 disabled:text-slate-400 flex items-center justify-center transition-colors"
              style={{ 
                backgroundColor: 'var(--user-bubble-bg)',
                color: 'var(--user-bubble-text)'
              }}
              onMouseEnter={(e) => {
                if (!e.currentTarget.disabled) {
                  e.currentTarget.style.opacity = '0.9';
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '';
              }}
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
