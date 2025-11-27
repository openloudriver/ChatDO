/**
 * Custom ChatComposer wrapper for Impact Workspace that adds context
 * from selected impacts and template fields to each message.
 */
import React, { useState, useRef, useEffect } from 'react';
import { useChatStore } from '../store/chat';
import type { ImpactEntry } from '../types/impact';
import type { Template } from '../utils/api';

interface ImpactWorkspaceChatComposerProps {
  selectedImpacts: ImpactEntry[];
  activeTemplate: Template | null;
  templateFieldValues: Record<string, string>;
  templateMode: 'none' | 'opb' | '1206';
  opbTemplate: Record<string, string>;
  form1206Text: string;
  supportingDocIds: string[];
}

export const ImpactWorkspaceChatComposer: React.FC<ImpactWorkspaceChatComposerProps> = ({
  selectedImpacts,
  activeTemplate,
  templateFieldValues,
  templateMode,
  opbTemplate,
  form1206Text,
  supportingDocIds,
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
  } = useChatStore();

  // Auto-resize textarea
  const adjustTextareaHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const scrollHeight = textareaRef.current.scrollHeight;
      const maxHeight = 300;
      const minHeight = 88;
      const newHeight = Math.min(Math.max(scrollHeight, minHeight), maxHeight);
      textareaRef.current.style.height = `${newHeight}px`;
    }
  };
  
  useEffect(() => {
    adjustTextareaHeight();
  }, [input]);

  const buildContextMessage = (): string => {
    const parts: string[] = [];
    
    parts.push("You are helping the user craft Air Force performance bullets. You have structured impact notes, an active OPB/1206 template, and supporting documents indexed in Memory Service. Use the Memory tool when you need more detail, but respect the template's character limits.");
    
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
    
    // Add template mode context
    if (templateMode === 'opb') {
      parts.push("\n=== OPB TEMPLATE (Performance Report) ===");
      parts.push("Current OPB sections with character limits:");
      const OPB_SECTIONS = [
        { key: 'dutyDescription', label: 'Duty Description', max: 450 },
        { key: 'executingTheMission', label: 'Executing the Mission', max: 350 },
        { key: 'leadingPeople', label: 'Leading People', max: 350 },
        { key: 'managingResources', label: 'Managing Resources', max: 350 },
        { key: 'improvingTheUnit', label: 'Improving the Unit', max: 350 },
        { key: 'higherLevelReviewer', label: 'Higher Level Reviewer Assessment', max: 250 },
      ];
      OPB_SECTIONS.forEach(section => {
        const value = opbTemplate[section.key] || "";
        const count = value.length;
        const over = count > section.max;
        parts.push(`- ${section.label} (max ${section.max} chars, current: ${count}${over ? ' - OVER LIMIT' : ''}): ${value ? `"${value}"` : "[empty]"}`);
      });
    } else if (templateMode === '1206') {
      parts.push("\n=== 1206 TEMPLATE (Award Package) ===");
      parts.push(`Current 1206 bullet (soft limit: 230 chars, current: ${form1206Text.length}):`);
      parts.push(form1206Text || "[empty]");
    }
    
    // Add reference PDF template context (if uploaded)
    if (activeTemplate) {
      parts.push("\n=== REFERENCE PDF TEMPLATE ===");
      parts.push(`Reference PDF: ${activeTemplate.filename} (for visual reference only)`);
      if (activeTemplate.fields.length > 0) {
        parts.push("\nPDF Template Fields (with current values and character limits):");
        activeTemplate.fields.forEach(field => {
          const fieldId = field.id || field.field_id || "";
          const fieldName = field.name || field.label || fieldId;
          const value = templateFieldValues[fieldId] || "";
          const maxChars = field.maxChars;
          const charInfo = maxChars ? ` (max ${maxChars} characters)` : " (no character limit)";
          parts.push(`- ${fieldName}${charInfo}: ${value ? `"${value}"` : "[empty - needs to be filled]"}`);
        });
      }
    }
    
    // Add supporting docs context
    if (supportingDocIds.length > 0) {
      parts.push("\n=== SUPPORTING DOCUMENTS ===");
      parts.push(`${supportingDocIds.length} supporting document(s) indexed in Memory Service. Use Memory tool to query these documents when you need additional context or evidence.`);
      parts.push(`Document IDs: ${supportingDocIds.join(", ")}`);
    }
    
    parts.push("\nUse the selected impacts to help draft content for the template fields. Respect character limits when provided. Query supporting documents via Memory tool when you need more detail.");
    
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
      textareaRef.current.style.height = 'auto';
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
          force_search: false
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
    <div className="px-4 py-3 border-t border-slate-700 bg-[#343541]">
      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message ChatDO about your impacts and template..."
            className="w-full rounded-lg border border-slate-600 bg-slate-800 px-4 py-3 pr-12 text-sm text-slate-100 placeholder-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
            rows={1}
            style={{ minHeight: '44px', maxHeight: '300px' }}
          />
        </div>
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          className="flex-shrink-0 w-10 h-10 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-400 text-white flex items-center justify-center transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
      {(selectedImpacts.length > 0 || templateMode !== 'none' || activeTemplate || supportingDocIds.length > 0) && (
        <div className="mt-2 text-xs text-slate-400">
          Context: {selectedImpacts.length} impact{selectedImpacts.length !== 1 ? "s" : ""} selected
          {templateMode !== 'none' && ` • Template: ${templateMode === 'opb' ? 'OPB' : '1206'}`}
          {activeTemplate && ` • PDF: ${activeTemplate.filename}`}
          {supportingDocIds.length > 0 && ` • ${supportingDocIds.length} supporting doc${supportingDocIds.length !== 1 ? 's' : ''}`}
        </div>
      )}
    </div>
  );
};

