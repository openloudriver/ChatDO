import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';
import axios from 'axios';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  projectId: string;
  targetName: string;
  createdAt: Date;
  trashed?: boolean;
  trashed_at?: string;
  thread_id?: string;
}

export interface Project {
  id: string;
  name: string;
  default_target: string;
  sort_index?: number;
}

export type ViewMode = 'projectList' | 'chat' | 'trashList' | 'search';

interface ChatStore {
  // State
  projects: Project[];
  currentProject: Project | null;
  conversations: Conversation[];
  trashedChats: Conversation[];
  currentConversation: Conversation | null;
  messages: Message[];
  isLoading: boolean;
  isStreaming: boolean;
  streamingContent: string;
  viewMode: ViewMode;
  searchResults: Conversation[];
  searchQuery: string;
  
  // Actions
  setProjects: (projects: Project[]) => void;
  setCurrentProject: (project: Project | null) => void;
  setViewMode: (mode: ViewMode) => void;
  loadProjects: () => Promise<void>;
  ensureGeneralProject: () => Promise<Project>;
  createNewChatInProject: (projectId: string) => Promise<Conversation>;
  createProject: (name: string) => Promise<void>;
  renameProject: (id: string, name: string) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  reorderProjects: (orderedIds: string[]) => Promise<void>;
  loadChats: (projectId?: string) => Promise<void>;
  loadTrashedChats: () => Promise<void>;
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  setCurrentConversation: (conversation: Conversation | null) => Promise<void>;
  renameChat: (id: string, title: string) => Promise<void>;
  deleteChat: (id: string) => Promise<void>;
  restoreChat: (id: string) => Promise<void>;
  purgeChat: (id: string) => Promise<void>;
  purgeAllTrashedChats: () => Promise<void>;
  ensureGeneralProject: () => Promise<Project>;
  createNewChatInProject: (projectId: string) => Promise<Conversation>;
  searchChats: (query: string) => Promise<void>;
  setSearchQuery: (query: string) => void;
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void;
  editMessage: (messageId: string, newContent: string) => void;
  deleteMessage: (messageId: string) => void;
  removeMessagesAfter: (messageId: string) => void;
  updateStreamingContent: (content: string) => void;
  setLoading: (loading: boolean) => void;
  setStreaming: (streaming: boolean) => void;
  clearStreaming: () => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  // Initial state
  projects: [],
  currentProject: null,
  conversations: [],
  trashedChats: [],
  currentConversation: null,
  messages: [],
  isLoading: false,
  isStreaming: false,
  streamingContent: '',
  viewMode: 'projectList',
  searchQuery: '',
  searchResults: [],
  
  // Actions
  setProjects: (projects) => set({ projects }),
  
  setCurrentProject: (project) => {
    // Persist last project to localStorage
    if (project) {
      localStorage.setItem('chatdo:lastProjectId', project.id);
    } else {
      localStorage.removeItem('chatdo:lastProjectId');
    }
    
    set((state) => ({
      currentProject: project,
      // Only set viewMode to projectList if a project is selected
      // If project is null, keep the current viewMode (could be trashList, etc.)
      viewMode: project ? 'projectList' : state.viewMode,
      currentConversation: null
    }));
  },
  
  setViewMode: (mode) => set({ viewMode: mode }),
  
  loadProjects: async () => {
    try {
      const response = await axios.get('http://localhost:8000/api/projects');
      const projects = response.data;
      set((state) => {
        // Don't auto-select project - let startup logic handle it
        // This allows session restore to work properly
        return { 
          projects
        };
      });
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  },
  
  createProject: async (name) => {
    try {
      const response = await axios.post('http://localhost:8000/api/projects', {
        name: name.trim()
      });
      const newProject = response.data;
      
      set((state) => ({
        projects: [...state.projects, newProject],
        currentProject: newProject
      }));
    } catch (error) {
      console.error('Failed to create project:', error);
      throw error;
    }
  },
  
  renameProject: async (id, name) => {
    try {
      const response = await axios.patch(`http://localhost:8000/api/projects/${id}`, {
        name: name.trim()
      });
      const updatedProject = response.data;
      
      set((state) => {
        const updatedProjects = state.projects.map(p =>
          p.id === id ? updatedProject : p
        );
        const updatedCurrentProject = state.currentProject?.id === id
          ? updatedProject
          : state.currentProject;
        
        return {
          projects: updatedProjects,
          currentProject: updatedCurrentProject
        };
      });
    } catch (error) {
      console.error('Failed to rename project:', error);
      throw error;
    }
  },
  
  deleteProject: async (id) => {
    try {
      await axios.delete(`http://localhost:8000/api/projects/${id}`);
      
      set((state) => {
        const updatedProjects = state.projects.filter(p => p.id !== id);
        const updatedCurrentProject = state.currentProject?.id === id
          ? (updatedProjects.length > 0 ? updatedProjects[0] : null)
          : state.currentProject;
        
        return {
          projects: updatedProjects,
          currentProject: updatedCurrentProject
        };
      });
    } catch (error) {
      console.error('Failed to delete project:', error);
      throw error;
    }
  },
  
  reorderProjects: async (orderedIds) => {
    try {
      // Optimistically update local state
      set((state) => {
        const projectMap = new Map(state.projects.map(p => [p.id, p]));
        const reorderedProjects = orderedIds
          .map(id => projectMap.get(id))
          .filter((p): p is Project => p !== undefined);
        
        // Add any projects not in the order list (defensive)
        const orderedSet = new Set(orderedIds);
        const remainingProjects = state.projects.filter(p => !orderedSet.has(p.id));
        reorderedProjects.push(...remainingProjects);
        
        return { projects: reorderedProjects };
      });
      
      // Call backend to persist the order
      const response = await axios.post('http://localhost:8000/api/projects/reorder', orderedIds);
      const updatedProjects = response.data;
      
      // Update with server response (which includes updated sort_index values)
      set({ projects: updatedProjects });
    } catch (error) {
      console.error('Failed to reorder projects:', error);
      // Reload projects to restore correct order on error
      const response = await axios.get('http://localhost:8000/api/projects');
      set({ projects: response.data });
      throw error;
    }
  },
  
  loadChats: async (projectId) => {
    try {
      // For project lists, only load active chats (not trashed)
      // For loading all chats (no projectId), include trashed to populate trashedChats
      const url = projectId
        ? `http://localhost:8000/api/chats?project_id=${projectId}&include_trashed=false`
        : `http://localhost:8000/api/chats?include_trashed=true`;
      const response = await axios.get(url);
      const allChats = response.data;
      
      // Get the project to find default_target
      const state = useChatStore.getState();
      const project = projectId 
        ? state.projects.find(p => p.id === projectId) || state.currentProject
        : state.currentProject;
      const defaultTarget = project?.default_target || 'general';
      
      // Find General project for fallback
      const generalProject = state.projects.find(p => p.name === 'General');
      
      // Convert to Conversation format and split active/trashed
      const activeChats: Conversation[] = [];
      const trashedChats: Conversation[] = [];
      
      for (const chat of allChats) {
        // Ensure every chat has a projectId (fallback to General if missing)
        const chatProjectId = chat.project_id || generalProject?.id;
        
        if (!chatProjectId) {
          // Skip chats without projectId if General doesn't exist (shouldn't happen, but be safe)
          console.warn('Chat without projectId and General project not found:', chat.id);
          continue;
        }
        
        // Get the actual project for this chat to determine target
        const chatProject = state.projects.find(p => p.id === chatProjectId);
        const chatTarget = chatProject?.default_target || 'general';
        
        const conversation: Conversation = {
          id: chat.id,
          title: chat.title,
          messages: [], // Will be populated with preview if available
          projectId: chatProjectId,
          targetName: chatTarget,
          createdAt: new Date(chat.created_at),
          trashed: chat.trashed || false,
          trashed_at: chat.trashed_at,
          thread_id: chat.thread_id
        };
        
        if (chat.trashed) {
          trashedChats.push(conversation);
        } else {
          activeChats.push(conversation);
        }
      }
      
      // Sort by updated_at (most recent first)
      const sortByDate = (a: Conversation, b: Conversation) => {
        const dateA = new Date(a.trashed_at || a.createdAt).getTime();
        const dateB = new Date(b.trashed_at || b.createdAt).getTime();
        return dateB - dateA;
      };
      
      activeChats.sort(sortByDate);
      trashedChats.sort(sortByDate);
      
      // Set conversations first (so UI can render immediately)
      set((state) => {
        // If current conversation was deleted, clear it or select another
        let newCurrentConversation = state.currentConversation;
        if (state.currentConversation) {
          const stillExists = allChats.some(c => c.id === state.currentConversation?.id);
          if (!stillExists) {
            newCurrentConversation = activeChats.length > 0 ? activeChats[0] : null;
          }
        }
        
        // When loading chats for a specific project, don't overwrite the global trashedChats
        // Only update trashedChats if we're loading all chats (no project filter)
        const update: any = {
          conversations: activeChats,
          currentConversation: newCurrentConversation
        };
        
        // Only update trashedChats if loading all chats (no project filter)
        if (!projectId) {
          update.trashedChats = trashedChats;
        }
        
        return update;
      });
      
      // Then load preview messages for each active chat (non-blocking)
      // Load more messages to find the last user message for preview
      for (const chat of activeChats) {
        if (chat.thread_id) {
          axios.get(`http://localhost:8000/api/chats/${chat.id}/messages?limit=10`)
            .then(response => {
              const previewMessages = response.data.messages || [];
              if (previewMessages.length > 0) {
                // Find the last user message (go backwards)
                let lastUserMsg = null;
                for (let i = previewMessages.length - 1; i >= 0; i--) {
                  if (previewMessages[i].role === 'user') {
                    lastUserMsg = previewMessages[i];
                    break;
                  }
                }
                
                // If no user message found, use the last message anyway
                const msgToShow = lastUserMsg || previewMessages[previewMessages.length - 1];
                
                const previewMessage: Message = {
                  id: `${chat.id}-preview`,
                  role: msgToShow.role,
                  content: msgToShow.content,
                  timestamp: new Date()
                };
                
                // Store all messages for preview (so getPreview can find user messages)
                const allPreviewMessages: Message[] = previewMessages.map((msg: any, idx: number) => ({
                  id: `${chat.id}-preview-${idx}`,
                  role: msg.role,
                  content: msg.content,
                  timestamp: new Date()
                }));
                
                // Update conversation with preview messages
                set((state) => ({
                  conversations: state.conversations.map(c =>
                    c.id === chat.id ? { ...c, messages: allPreviewMessages } : c
                  )
                }));
              }
            })
            .catch(err => {
              // Silently fail - preview is optional
              console.debug('Failed to load preview for chat:', chat.id, err);
            });
        }
      }
    } catch (error) {
      console.error('Failed to load chats:', error);
    }
  },
  
  loadTrashedChats: async () => {
    try {
      const response = await axios.get('http://localhost:8000/api/chats?include_trashed=true');
      const allChats = response.data;
      
      const state = useChatStore.getState();
      const trashedChats: Conversation[] = [];
      
      for (const chat of allChats) {
        if (chat.trashed) {
          const project = state.projects.find(p => p.id === chat.project_id);
          const defaultTarget = project?.default_target || 'general';
          
          const conversation: Conversation = {
            id: chat.id,
            title: chat.title,
            messages: [],
            projectId: chat.project_id,
            targetName: defaultTarget,
            createdAt: new Date(chat.created_at),
            trashed: true,
            trashed_at: chat.trashed_at,
            thread_id: chat.thread_id
          };
          
          trashedChats.push(conversation);
        }
      }
      
      // Sort by trashed_at (most recent first)
      trashedChats.sort((a, b) => {
        const dateA = new Date(a.trashed_at || a.createdAt).getTime();
        const dateB = new Date(b.trashed_at || b.createdAt).getTime();
        return dateB - dateA;
      });
      
      set({ trashedChats });
    } catch (error) {
      console.error('Failed to load trashed chats:', error);
    }
  },
  
  setConversations: (conversations) => set({ conversations }),
  
  addConversation: (conversation) => set((state) => ({
    conversations: [conversation, ...state.conversations]
  })),
  
  renameChat: async (id, title) => {
    try {
      const response = await axios.patch(`http://localhost:8000/api/chats/${id}`, {
        title: title.trim()
      });
      const updatedChat = response.data;
      
      set((state) => {
        const updatedConversations = state.conversations.map(c =>
          c.id === id ? { ...c, title: updatedChat.title } : c
        );
        const updatedTrashedChats = state.trashedChats.map(c =>
          c.id === id ? { ...c, title: updatedChat.title } : c
        );
        const updatedCurrentConversation = state.currentConversation?.id === id
          ? { ...state.currentConversation, title: updatedChat.title }
          : state.currentConversation;
        
        return {
          conversations: updatedConversations,
          trashedChats: updatedTrashedChats,
          currentConversation: updatedCurrentConversation
        };
      });
    } catch (error) {
      console.error('Failed to rename chat:', error);
      throw error;
    }
  },
  
  deleteChat: async (id) => {
    try {
      const response = await axios.delete(`http://localhost:8000/api/chats/${id}`);
      const deletedChat = response.data;
      
      // Get the project to find default_target
      const state = useChatStore.getState();
      const project = state.projects.find(p => p.id === deletedChat.project_id) || state.currentProject;
      const defaultTarget = project?.default_target || 'general';
      
      // Convert backend response to Conversation format
      const trashedConversation: Conversation = {
        id: deletedChat.id,
        title: deletedChat.title,
        messages: state.currentConversation?.id === id ? state.currentConversation.messages : [],
        projectId: deletedChat.project_id,
        targetName: defaultTarget,
        createdAt: new Date(deletedChat.created_at),
        trashed: true,
        trashed_at: deletedChat.trashed_at,
        thread_id: deletedChat.thread_id
      };
      
      set((state) => {
        const updatedConversations = state.conversations.filter(c => c.id !== id);
        
        // If deleted chat was current, select another or clear
        const updatedCurrentConversation = state.currentConversation?.id === id
          ? (updatedConversations.length > 0 ? updatedConversations[0] : null)
          : state.currentConversation;
        
        // Add to trashed chats (avoid duplicates)
        const updatedTrashedChats = state.trashedChats.some(c => c.id === id)
          ? state.trashedChats
          : [trashedConversation, ...state.trashedChats];
        
        return {
          conversations: updatedConversations,
          trashedChats: updatedTrashedChats,
          currentConversation: updatedCurrentConversation
        };
      });
      
      // Reload chats to ensure we have the latest state
      // Small delay to ensure backend has saved the change
      await new Promise(resolve => setTimeout(resolve, 200));
      
      if (deletedChat.project_id) {
        await useChatStore.getState().loadChats(deletedChat.project_id);
      }
      // Also reload trashed chats so it appears in Trash view
      await useChatStore.getState().loadTrashedChats();
    } catch (error) {
      console.error('Failed to delete chat:', error);
      throw error;
    }
  },
  
  restoreChat: async (id) => {
    try {
      const response = await axios.post(`http://localhost:8000/api/chats/${id}/restore`);
      const restoredChat = response.data;
      
      set((state) => {
        const chat = state.trashedChats.find(c => c.id === id);
        const updatedTrashedChats = state.trashedChats.filter(c => c.id !== id);
        // Get default_target from the project
        const project = state.projects.find(p => p.id === restoredChat.project_id) || state.currentProject;
        const defaultTarget = project?.default_target || 'general';
        const restoredConversation: Conversation = {
          id: restoredChat.id,
          title: restoredChat.title,
          messages: chat?.messages || [],
          projectId: restoredChat.project_id,
          targetName: chat?.targetName || defaultTarget,
          createdAt: new Date(restoredChat.created_at),
          trashed: false,
          trashed_at: undefined,
          thread_id: restoredChat.thread_id
        };
        const updatedConversations = [restoredConversation, ...state.conversations];
        
        return {
          conversations: updatedConversations,
          trashedChats: updatedTrashedChats
        };
      });
    } catch (error) {
      console.error('Failed to restore chat:', error);
      throw error;
    }
  },
  
  purgeChat: async (id) => {
    try {
      // Get the chat's project before purging so we can reload its chats
      const state = useChatStore.getState();
      const chatToPurge = state.trashedChats.find(c => c.id === id);
      const projectId = chatToPurge?.projectId;
      
      await axios.post(`http://localhost:8000/api/chats/${id}/purge`);
      
      set((state) => {
        const updatedTrashedChats = state.trashedChats.filter(c => c.id !== id);
        
        // If purged chat was current, clear it
        const updatedCurrentConversation = state.currentConversation?.id === id
          ? null
          : state.currentConversation;
        
        return {
          trashedChats: updatedTrashedChats,
          currentConversation: updatedCurrentConversation
        };
      });
      
      // Reload project chats to ensure the purged chat is gone
      if (projectId) {
        await useChatStore.getState().loadChats(projectId);
      }
    } catch (error) {
      console.error('Failed to purge chat:', error);
      throw error;
    }
  },
  
  purgeAllTrashedChats: async () => {
    try {
      // Get all project IDs that have trashed chats before purging
      const state = useChatStore.getState();
      const projectIds = new Set(state.trashedChats.map(c => c.projectId).filter(Boolean));
      
      const response = await axios.post('http://localhost:8000/api/chats/purge_all_trashed');
      
      // Clear all trashed chats and reload
      set((state) => {
        // If current conversation is trashed, clear it
        const updatedCurrentConversation = state.currentConversation?.trashed
          ? null
          : state.currentConversation;
        
        return {
          trashedChats: [],
          currentConversation: updatedCurrentConversation
        };
      });
      
      // Reload all affected project chats to ensure purged chats are gone
      for (const projectId of projectIds) {
        await useChatStore.getState().loadChats(projectId);
      }
      
      // Reload trashed chats to ensure UI is in sync (should be empty now)
      await useChatStore.getState().loadTrashedChats();
    } catch (error) {
      console.error('Failed to purge all trashed chats:', error);
      throw error;
    }
  },
  
  setCurrentConversation: async (conversation) => {
    if (!conversation) {
      localStorage.removeItem('chatdo:lastChatId');
      set({ 
        currentConversation: null,
        messages: [],
        viewMode: 'projectList'
      });
      return;
    }
    
    // Persist last chat and project to localStorage
    localStorage.setItem('chatdo:lastChatId', conversation.id);
    // Also save the project ID if we have it
    if (conversation.projectId) {
      localStorage.setItem('chatdo:lastProjectId', conversation.projectId);
    }
    
    // Set conversation immediately
    set({ 
      currentConversation: conversation,
      viewMode: 'chat'
    });
    
    // Load messages from backend
    try {
      const response = await axios.get(`http://localhost:8000/api/chats/${conversation.id}/messages`);
      const backendMessages = response.data.messages || [];
      
      // Convert backend messages to frontend format
      const messages: Message[] = backendMessages.map((msg: any, index: number) => ({
        id: `${conversation.id}-${index}`,
        role: msg.role,
        content: msg.content,
        timestamp: new Date() // Backend doesn't provide timestamps, use current time
      }));
      
      // Update conversation object with messages so preview works
      const updatedConversation = {
        ...conversation,
        messages: messages
      };
      
      set((state) => ({
        messages,
        currentConversation: updatedConversation,
        // Update conversation in conversations list so preview shows
        conversations: state.conversations.map(c =>
          c.id === conversation.id ? updatedConversation : c
        )
      }));
    } catch (error) {
      console.error('Failed to load messages:', error);
      // If loading fails, use messages from conversation object (might be empty)
      set({ messages: conversation.messages || [] });
    }
  },
  
  addMessage: (message) => set((state) => {
    const newMessage: Message = {
      ...message,
      id: uuidv4(),
      timestamp: new Date()
    };
    
    const updatedMessages = [...state.messages, newMessage];
    
    // Update conversation if it exists
    if (state.currentConversation) {
      const updatedConversation = {
        ...state.currentConversation,
        messages: updatedMessages
      };
      
      return {
        messages: updatedMessages,
        conversations: state.conversations.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        trashedChats: state.trashedChats.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        currentConversation: updatedConversation
      };
    }
    
    return { messages: updatedMessages };
  }),
  
  editMessage: (messageId, newContent) => set((state) => {
    const updatedMessages = state.messages.map(msg =>
      msg.id === messageId ? { ...msg, content: newContent } : msg
    );
    
    if (state.currentConversation) {
      const updatedConversation = {
        ...state.currentConversation,
        messages: updatedMessages
      };
      
      return {
        messages: updatedMessages,
        conversations: state.conversations.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        trashedChats: state.trashedChats.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        currentConversation: updatedConversation
      };
    }
    
    return { messages: updatedMessages };
  }),
  
  deleteMessage: (messageId) => set((state) => {
    const messageIndex = state.messages.findIndex(msg => msg.id === messageId);
    if (messageIndex === -1) return state;
    
    // Remove the message and all messages after it
    const updatedMessages = state.messages.slice(0, messageIndex);
    
    if (state.currentConversation) {
      const updatedConversation = {
        ...state.currentConversation,
        messages: updatedMessages
      };
      
      return {
        messages: updatedMessages,
        conversations: state.conversations.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        trashedChats: state.trashedChats.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        currentConversation: updatedConversation
      };
    }
    
    return { messages: updatedMessages };
  }),
  
  removeMessagesAfter: (messageId) => set((state) => {
    const messageIndex = state.messages.findIndex(msg => msg.id === messageId);
    if (messageIndex === -1) return state;
    
    // Keep messages up to and including the specified message
    const updatedMessages = state.messages.slice(0, messageIndex + 1);
    
    if (state.currentConversation) {
      const updatedConversation = {
        ...state.currentConversation,
        messages: updatedMessages
      };
      
      return {
        messages: updatedMessages,
        conversations: state.conversations.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        trashedChats: state.trashedChats.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        currentConversation: updatedConversation
      };
    }
    
    return { messages: updatedMessages };
  }),
  
  updateStreamingContent: (content) => set({ streamingContent: content }),
  
  setLoading: (loading) => set({ isLoading: loading }),
  
  setStreaming: (streaming) => set({ isStreaming: streaming }),
  
  clearStreaming: () => set({ isStreaming: false, streamingContent: '' }),
  
  ensureGeneralProject: async () => {
    const state = useChatStore.getState();
    let generalProject = state.projects.find(p => p.name === 'General');
    
    if (!generalProject) {
      // Create General project if it doesn't exist
      try {
        const response = await axios.post('http://localhost:8000/api/projects', {
          name: 'General'
        });
        generalProject = response.data;
        
        set((state) => ({
          projects: [generalProject, ...state.projects],
          currentProject: state.currentProject || generalProject
        }));
      } catch (error) {
        console.error('Failed to create General project:', error);
        throw error;
      }
    }
    
    return generalProject;
  },
  
  createNewChatInProject: async (projectId: string) => {
    try {
      const response = await axios.post('http://localhost:8000/api/new_conversation', {
        project_id: projectId
      });
      const conversationId = response.data.conversation_id;
      
      // Reload chats to get the new one
      await useChatStore.getState().loadChats(projectId);
      
      // Find and return the new conversation
      const state = useChatStore.getState();
      const newConversation = state.conversations.find(c => c.id === conversationId);
      
      if (!newConversation) {
        throw new Error('Failed to find newly created conversation');
      }
      
      return newConversation;
    } catch (error) {
      console.error('Failed to create new chat:', error);
      throw error;
    }
  },
  
  setSearchQuery: (query) => {
    set({ searchQuery: query });
    // If query is cleared, exit search mode
    if (!query.trim()) {
      set((state) => {
        // Return to projectList if we were in search mode
        const newViewMode = state.viewMode === 'search' ? 'projectList' : state.viewMode;
        return { 
          searchResults: [],
          viewMode: newViewMode
        };
      });
    }
  },
  
  searchChats: async (query: string) => {
    if (!query.trim()) {
      set((state) => {
        const newViewMode = state.viewMode === 'search' ? 'projectList' : state.viewMode;
        return { 
          searchResults: [],
          viewMode: newViewMode
        };
      });
      return;
    }
    
    try {
      // Load all chats (not filtered by project)
      const response = await axios.get('http://localhost:8000/api/chats?include_trashed=false');
      const allChats = response.data;
      
      const state = useChatStore.getState();
      const queryLower = query.toLowerCase().trim();
      const results: Conversation[] = [];
      
      // Search through all chats
      for (const chat of allChats) {
        // Search in title
        const titleMatch = chat.title?.toLowerCase().includes(queryLower);
        
        // Search in messages (load preview messages)
        let contentMatch = false;
        if (chat.thread_id) {
          try {
            const msgResponse = await axios.get(`http://localhost:8000/api/chats/${chat.id}/messages?limit=10`);
            const messages = msgResponse.data.messages || [];
            for (const msg of messages) {
              if (msg.content?.toLowerCase().includes(queryLower)) {
                contentMatch = true;
                break;
              }
            }
          } catch (err) {
            // If we can't load messages, just skip content search for this chat
          }
        }
        
        if (titleMatch || contentMatch) {
          const project = state.projects.find(p => p.id === chat.project_id);
          const defaultTarget = project?.default_target || 'general';
          
          const conversation: Conversation = {
            id: chat.id,
            title: chat.title,
            messages: [], // Will be loaded when opened
            projectId: chat.project_id,
            targetName: defaultTarget,
            createdAt: new Date(chat.created_at),
            trashed: false,
            trashed_at: undefined,
            thread_id: chat.thread_id
          };
          
          results.push(conversation);
        }
      }
      
      // Sort by relevance (title matches first, then by date)
      results.sort((a, b) => {
        const aTitleMatch = a.title.toLowerCase().includes(queryLower);
        const bTitleMatch = b.title.toLowerCase().includes(queryLower);
        if (aTitleMatch && !bTitleMatch) return -1;
        if (!aTitleMatch && bTitleMatch) return 1;
        return b.createdAt.getTime() - a.createdAt.getTime();
      });
      
      set({ 
        searchResults: results,
        viewMode: 'search'
      });
    } catch (error) {
      console.error('Failed to search chats:', error);
      set({ searchResults: [] });
    }
  }
}));

