import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';
import axios from 'axios';
import type { Source } from '../types/sources';
import type { RagFile } from '../types/rag';

// Configure axios to suppress 404 errors in console for chat message endpoints
// (These are expected when chats don't exist or have no messages)
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    // Suppress 404 errors for chat message endpoints (expected for deleted/non-existent chats)
    if (error.config?.url?.includes('/api/chats/') && error.config?.url?.includes('/messages')) {
      if (error.response?.status === 404) {
        // Return a rejected promise but don't log to console
        return Promise.reject(error);
      }
    }
    // For all other errors, let them through normally
    return Promise.reject(error);
  }
);

export interface Message {
  id: string;
  uuid?: string;  // Stable UUID from backend for deep-linking (message_uuid)
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  type?: 'text' | 'web_search_results' | 'article_card' | 'document_card' | 'compare_articles_card' | 'timeline_card' | 'rag_response';  // Message types
  model?: string;  // Model used (e.g., "GPT-5", "Brave Search", "Trafilatura + GPT-5")
  model_label?: string;  // Full model label from backend (e.g., "Model: Memory + GPT-5", "Model: Brave + GPT-5")
  provider?: string;  // Provider used (e.g., "openai-gpt5", "brave_search", "trafilatura-gpt5")
  sources?: Source[];  // Source objects for citations (ChatGPT-style)
  data?: {
    query?: string;
    provider?: string;
    results?: Array<{ title: string; url: string; snippet: string; published_at?: string; age?: string; page_age?: string }>;
    summary?: string | {
      text: string;
      citations?: Array<{ title: string; url: string; domain: string }>;
    } | null;
    url?: string;
    domain?: string;
    content?: string;
    // Document card properties
    fileName?: string;
    fileType?: string;
    filePath?: string;
    keyPoints?: string[];
    whyMatters?: string;
    estimatedReadTimeMinutes?: number;
    wordCount?: number;
    pageCount?: number;
    // Article card properties
    title?: string;
    siteName?: string;
    published?: string;
    meta?: {
      usedWebSearch?: boolean;
      webResultsPreview?: Array<{ title: string; url: string; snippet: string }>;
    };
  };  // Structured data for special message types
  meta?: {
    usedWebSearch?: boolean;
    webResultsPreview?: Array<{ title: string; url: string; snippet: string }>;
    index_job?: {
      user_job_id?: string | null;
      assistant_job_id?: string | null;
    };
    index_status?: string;  // "P" or "F"
    facts_actions?: {
      S?: number;
      U?: number;
      R?: number;
      F?: boolean;
    };
    files_actions?: {
      R?: number;
    };
  };  // Metadata for messages (e.g., web search usage, indexing jobs)
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  projectId: string;
  targetName: string;
  createdAt: Date;
  updatedAt?: string;  // ISO string from backend updated_at
  trashed?: boolean;
  trashed_at?: string;
  archived?: boolean;
  archived_at?: string;
  thread_id?: string;
}

export interface Project {
  id: string;
  name: string;
  default_target: string;
  sort_index?: number;
  trashed?: boolean;
  trashed_at?: string;
  archived?: boolean;
  archived_at?: string;
}

export type ViewMode = 'projectList' | 'chat' | 'trashList' | 'search' | 'memory' | 'impact' | 'library';
export type WebMode = 'auto' | 'on';

export interface ConnectProjectModalState {
  open: boolean;
  projectId?: string;
  projectName?: string;
}

interface ChatStore {
  // State
  projects: Project[];
  currentProject: Project | null;
  conversations: Conversation[];
  allConversations: Conversation[];  // All conversations across all projects (for Recent section)
  trashedChats: Conversation[];
  currentConversation: Conversation | null;
  messages: Message[];
  isLoading: boolean;
  isStreaming: boolean;
  streamingContent: string;
  isSummarizingArticle: boolean;  // Shared state for article summarization (deprecated - use per-conversation)
  summarizingConversations: Set<string>;  // Track which conversations are currently summarizing
  isRagTrayOpen: boolean;  // Whether RAG context tray is open
  viewMode: ViewMode;
  searchResults: Conversation[];
  searchQuery: string;
  sources: Source[];  // Sources for current conversation
  ragFileIds: string[];  // RAG file IDs for current conversation (deprecated - use ragFilesByConversationId)
  ragFilesByConversationId: Record<string, RagFile[]>;  // RAG files scoped per conversation
  connectProjectModal: ConnectProjectModalState;  // Connect Project modal state
  webMode: WebMode;  // Web search mode: 'auto' (default) or 'on' (forced)
  
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
  moveChat: (id: string, projectId: string) => Promise<void>;
  restoreChat: (id: string) => Promise<void>;
  purgeChat: (id: string) => Promise<void>;
  purgeAllTrashedChats: () => Promise<void>;
  searchChats: (query: string, scope?: string) => Promise<void>;
  setSearchQuery: (query: string) => void;
  searchScope: string;  // 'all', 'active', 'archived', 'trash'
  setSearchScope: (scope: string) => void;
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void;
  openConnectProjectModal: (projectId: string, projectName: string) => void;
  closeConnectProjectModal: () => void;
  editMessage: (messageId: string, newContent: string) => void;
  deleteMessage: (messageId: string) => void;
  removeMessagesAfter: (messageId: string) => void;
  updateStreamingContent: (content: string) => void;
  setLoading: (loading: boolean) => void;
  setStreaming: (streaming: boolean) => void;
  clearStreaming: () => void;
  setSummarizingArticle: (summarizing: boolean) => void;  // Deprecated - kept for backward compatibility
  setConversationSummarizing: (conversationId: string | null, isSummarizing: boolean) => void;
  isConversationSummarizing: (conversationId: string | null) => boolean;
  setRagTrayOpen: (open: boolean) => void;
  setRagFileIds: (ids: string[]) => void;
  setRagFilesForConversation: (conversationId: string, files: RagFile[]) => void;
  getRagFilesForConversation: (conversationId: string | null) => RagFile[];
  addSource: (source: Source) => void;
  setSources: (sources: Source[]) => void;
  loadSources: (conversationId: string) => Promise<void>;
  setWebMode: (mode: WebMode) => void;
}

// @ts-ignore - Zustand circular reference pattern (store references itself)
export const useChatStore = create<ChatStore>((set) => ({
  // Initial state
  projects: [],
  currentProject: null,
  conversations: [],
  allConversations: [],  // All conversations across all projects
  trashedChats: [],
  currentConversation: null,
  messages: [],
  isLoading: false,
  isStreaming: false,
  streamingContent: '',
  isSummarizingArticle: false,  // Deprecated - kept for backward compatibility
  summarizingConversations: new Set<string>(),
  isRagTrayOpen: false,
  viewMode: (() => {
    // Restore viewMode from localStorage on initialization
    const saved = localStorage.getItem('chatdo:viewMode');
    if (saved && ['projectList', 'chat', 'trashList', 'search', 'memory', 'impact', 'library'].includes(saved)) {
      return saved as ViewMode;
    }
    return 'projectList';
  })(),
  searchQuery: '',
  searchResults: [],
  searchScope: 'all',  // Default: search all (active + archived)
  sources: [],
  ragFileIds: [],
  ragFilesByConversationId: {},
  connectProjectModal: { open: false },
  webMode: 'auto' as WebMode,
  
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
      // Only set viewMode to projectList if a project is selected AND we're not in a special view mode
      // Special view modes (impact, memory) should not be overridden
      // If project is null, keep the current viewMode (could be trashList, etc.)
      viewMode: project && !['impact', 'memory'].includes(state.viewMode) ? 'projectList' : state.viewMode,
      currentConversation: null
    }));
  },
  
  setViewMode: (mode) => {
    // Persist viewMode to localStorage
    localStorage.setItem('chatdo:viewMode', mode);
    set({ viewMode: mode });
  },
  
  loadProjects: async () => {
    try {
      // Load only active projects (excludes archived and trashed)
      const response = await axios.get('http://localhost:8000/api/projects?scope=active');
      const projects = response.data;
      set(() => {
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

      // Automatically create a new chat in the new project and switch to it
      const { createNewChatInProject, setCurrentConversation, setViewMode } = useChatStore.getState();
      const newConversation = await createNewChatInProject(newProject.id);
      await setCurrentConversation(newConversation);
      setViewMode('chat');
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
        // Filter out the deleted project (it's now trashed)
        const updatedProjects = state.projects.filter(p => p.id !== id);
        const wasCurrentProject = state.currentProject?.id === id;
        const updatedCurrentProject = wasCurrentProject
          ? (updatedProjects.length > 0 ? updatedProjects[0] : null)
          : state.currentProject;
        
        // If the deleted project was the current project, clear current conversation
        // Also clear any conversations that belonged to the deleted project
        const updatedCurrentConversation = wasCurrentProject || state.currentConversation?.projectId === id
          ? null
          : state.currentConversation;
        
        // Remove all conversations that belonged to the deleted project from active lists
        // (They are now trashed on the backend, so they'll be in trashedChats after reload)
        const updatedConversations = state.conversations.filter(c => c.projectId !== id);
        const updatedAllConversations = state.allConversations.filter(c => c.projectId !== id);
        
        return {
          projects: updatedProjects,
          currentProject: updatedCurrentProject,
          currentConversation: updatedCurrentConversation,
          conversations: updatedConversations,
          allConversations: updatedAllConversations
        };
      });
      
      // Reload chats to ensure we have the latest state after project deletion
      const state = useChatStore.getState();
      if (state.currentProject) {
        await state.loadChats(state.currentProject.id);
      }
      // Reload all chats (including trashed) to update allConversations and trashedChats
      // This will pick up the chats that were soft-deleted when the project was deleted
      await useChatStore.getState().loadChats();
      await useChatStore.getState().loadTrashedChats();
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
      // For project lists, only load active chats (not trashed, not archived)
      // For loading all chats (no projectId), use scope=all to get active+archived (for Recent section)
      const url = projectId
        ? `http://localhost:8000/api/chats?project_id=${projectId}&scope=active`
        : `http://localhost:8000/api/chats?scope=all`;
      const response = await axios.get(url);
      const allChats = response.data;
      
      // Get the project to find default_target
      const state = useChatStore.getState();
      
      // Find General project for fallback
      const generalProject = state.projects.find((p: Project) => p.name === 'General');
      
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
        const chatProject = state.projects.find((p: Project) => p.id === chatProjectId);
        const chatTarget = chatProject?.default_target || 'general';
        
        const conversation: Conversation = {
          id: chat.id,
          title: chat.title,
          messages: [], // Will be populated with preview if available
          projectId: chatProjectId,
          targetName: chatTarget,
          createdAt: new Date(chat.created_at),
          updatedAt: chat.updated_at,  // Map updated_at from backend
          trashed: chat.trashed || false,
          trashed_at: chat.trashed_at,
          archived: chat.archived || false,
          archived_at: chat.archived_at,
          thread_id: chat.thread_id
        };
        
        if (chat.trashed) {
          trashedChats.push(conversation);
        } else if (!chat.archived) {
          // Only add to activeChats if not trashed and not archived
          activeChats.push(conversation);
        }
        // Note: archived chats are included in allConversations (for Recent section)
        // but excluded from activeChats (default list views)
      }
      
      // Sort by updated_at (most recent first)
      // For active chats, use updatedAt (fallback to createdAt)
      // For trashed chats, use trashed_at (fallback to createdAt)
      const sortActiveChats = (a: Conversation, b: Conversation) => {
        const aTime = a.updatedAt ? new Date(a.updatedAt).getTime() : (a.createdAt ? new Date(a.createdAt).getTime() : 0);
        const bTime = b.updatedAt ? new Date(b.updatedAt).getTime() : (b.createdAt ? new Date(b.createdAt).getTime() : 0);
        return bTime - aTime;
      };
      
      const sortTrashedChats = (a: Conversation, b: Conversation) => {
        const dateA = new Date(a.trashed_at || a.createdAt).getTime();
        const dateB = new Date(b.trashed_at || b.createdAt).getTime();
        return dateB - dateA;
      };
      
      activeChats.sort(sortActiveChats);
      trashedChats.sort(sortTrashedChats);
      
      // Set conversations first (so UI can render immediately)
      set((state) => {
        // If current conversation was deleted, clear it or select another
        let newCurrentConversation = state.currentConversation;
        if (state.currentConversation) {
          const stillExists = allChats.some((c: any) => c.id === state.currentConversation?.id);
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
        
        // If loading all chats (no project filter), update allConversations and trashedChats
        // Note: allConversations should only include active chats (excludes archived and trashed)
        // Archived chats are searchable via search scope but don't appear in default lists
        if (!projectId) {
          update.allConversations = activeChats;  // Update global list with all active chats (excludes archived)
          update.trashedChats = trashedChats;
        } else {
          // When loading a specific project's chats, merge into allConversations
          // Remove old chats for this project and add new ones
          // Keep chats from other projects
          const otherProjectChats = state.allConversations.filter(
            c => c.projectId !== projectId
          );
          // Merge and deduplicate by id, keeping the most recent version
          const merged = [...otherProjectChats, ...activeChats];
          const deduplicated = new Map<string, Conversation>();
          for (const chat of merged) {
            if (!chat.id) continue;
            const existing = deduplicated.get(chat.id);
            if (!existing) {
              deduplicated.set(chat.id, chat);
            } else {
              // Keep the one with the more recent updatedAt
              const existingTime = existing.updatedAt ?? existing.createdAt?.toISOString() ?? '';
              const newTime = chat.updatedAt ?? chat.createdAt?.toISOString() ?? '';
              if (newTime > existingTime) {
                deduplicated.set(chat.id, chat);
              }
            }
          }
          update.allConversations = Array.from(deduplicated.values());
        }
        
        return update;
      });
      
      // Then load preview messages for each active chat (non-blocking)
      // Only load previews for chats that:
      // 1. Have a thread_id (exist in backend)
      // 2. Are in the current activeChats list (not stale/deleted)
      // 3. Only when loading a specific project (not when loading all chats globally)
      // This prevents 404s from trying to load previews for deleted chats
      if (projectId) {
        for (const chat of activeChats) {
          if (chat.thread_id && chat.id) {
            // Use a small delay to batch requests and avoid overwhelming the server
            setTimeout(() => {
              axios.get(`http://localhost:8000/api/chats/${chat.id}/messages?limit=10`, {
                validateStatus: (status) => status < 500 // Don't throw on 404, just catch it
              })
                .then(response => {
                  // Verify the chat still exists in activeChats before updating
                  const state = useChatStore.getState();
                  const chatStillExists = state.conversations.some((c: Conversation) => c.id === chat.id) || 
                                         state.allConversations.some((c: Conversation) => c.id === chat.id);
                  
                  if (!chatStillExists) {
                    // Chat was deleted, don't update
                    return;
                  }
                  
                  const previewMessages = response.data.messages || [];
                  if (previewMessages.length > 0) {
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
                      ),
                      allConversations: state.allConversations.map(c =>
                        c.id === chat.id ? { ...c, messages: allPreviewMessages } : c
                      )
                    }));
                  }
                })
                .catch(() => {
                  // Silently ignore all errors - preview is optional
                  // Don't log anything to console to keep it clean
                });
            }, Math.random() * 100); // Small random delay to batch requests
          }
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
          const project = state.projects.find((p: Project) => p.id === chat.project_id);
          const defaultTarget = project?.default_target || 'general';
          
          const conversation: Conversation = {
            id: chat.id,
            title: chat.title,
            messages: [],
            projectId: chat.project_id,
            targetName: defaultTarget,
            createdAt: new Date(chat.created_at),
            updatedAt: chat.updated_at,  // Map updated_at from backend
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
    conversations: [conversation, ...state.conversations],
    allConversations: [conversation, ...state.allConversations]
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
        const updatedAllConversations = state.allConversations.map(c =>
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
          allConversations: updatedAllConversations,
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
      const project = state.projects.find((p: Project) => p.id === deletedChat.project_id) || state.currentProject;
      const defaultTarget = project?.default_target || 'general';
      
      // Convert backend response to Conversation format
      const trashedConversation: Conversation = {
        id: deletedChat.id,
        title: deletedChat.title,
        messages: state.currentConversation?.id === id ? state.currentConversation.messages : [],
        projectId: deletedChat.project_id,
        targetName: defaultTarget,
        createdAt: new Date(deletedChat.created_at),
        updatedAt: deletedChat.updated_at,  // Map updated_at from backend
        trashed: true,
        trashed_at: deletedChat.trashed_at,
        thread_id: deletedChat.thread_id
      };
      
      set((state) => {
        const updatedConversations = state.conversations.filter(c => c.id !== id);
        const updatedAllConversations = state.allConversations.filter(c => c.id !== id);
        
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
          allConversations: updatedAllConversations,
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
  
  moveChat: async (id, projectId) => {
    try {
      await axios.post(`http://localhost:8000/api/chats/${id}/move`, {
        project_id: projectId
      });
      
      // Get the project to find default_target
      const state = useChatStore.getState();
      const project = state.projects.find((p: Project) => p.id === projectId) || state.currentProject;
      const defaultTarget = project?.default_target || 'general';
      
      // Update the chat's project_id in all state arrays
      set((state) => {
        const updatedConversations = state.conversations.map((c: Conversation) =>
          c.id === id ? { ...c, projectId: projectId, targetName: defaultTarget } : c
        );
        const updatedAllConversations = state.allConversations.map((c: Conversation) =>
          c.id === id ? { ...c, projectId: projectId, targetName: defaultTarget } : c
        );
        const updatedTrashedChats = state.trashedChats.map((c: Conversation) =>
          c.id === id ? { ...c, projectId: projectId, targetName: defaultTarget } : c
        );
        const updatedCurrentConversation = state.currentConversation?.id === id
          ? { ...state.currentConversation, projectId: projectId, targetName: defaultTarget }
          : state.currentConversation;
        
        return {
          conversations: updatedConversations,
          allConversations: updatedAllConversations,
          trashedChats: updatedTrashedChats,
          currentConversation: updatedCurrentConversation
        };
      });
      
      // Reload chats for the old project (if we're viewing it) to remove the moved chat
      const oldProjectId = state.currentProject?.id;
      if (oldProjectId && oldProjectId !== projectId) {
        await useChatStore.getState().loadChats(oldProjectId);
      }
      // Also reload all chats to update Recent Chats in sidebar
      await useChatStore.getState().loadChats();
    } catch (error) {
      console.error('Failed to move chat:', error);
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
          updatedAt: restoredChat.updated_at,  // Map updated_at from backend
          trashed: false,
          trashed_at: undefined,
          thread_id: restoredChat.thread_id
        };
        const updatedConversations = [restoredConversation, ...state.conversations];
        const updatedAllConversations = [restoredConversation, ...state.allConversations];
        
        return {
          conversations: updatedConversations,
          allConversations: updatedAllConversations,
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
      const chatToPurge = state.trashedChats.find((c: Conversation) => c.id === id);
      const projectId = chatToPurge?.projectId;
      
      await axios.post(`http://localhost:8000/api/chats/${id}/purge`);
      
      set((state) => {
        const updatedTrashedChats = state.trashedChats.filter((c: Conversation) => c.id !== id);
        
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
      const projectIds = new Set(state.trashedChats.map((c: Conversation) => c.projectId).filter(Boolean));
      
      await axios.post('http://localhost:8000/api/chats/purge_all_trashed');
      
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
      // Clear URL hash when clearing conversation
      if (typeof window !== 'undefined' && window.location.hash) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      }
      set({ 
        currentConversation: null,
        messages: [],
        viewMode: 'projectList',
        ragFileIds: [],  // Clear RAG files when conversation is cleared
        // Note: ragFilesByConversationId is preserved so switching back works
      });
      return;
    }
    
    // Clear URL hash when switching to a new conversation (will be set by deep-link if needed)
    // This prevents old hashes from persisting across conversation switches
    if (typeof window !== 'undefined' && window.location.hash) {
      const hash = window.location.hash;
      // Only clear if it's a message hash (we'll set a new one if deep-linking is needed)
      if (hash.startsWith('#message-')) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      }
    }
    
    // Persist last chat and project to localStorage
    localStorage.setItem('chatdo:lastChatId', conversation.id);
    // Also save the project ID if we have it
    if (conversation.projectId) {
      localStorage.setItem('chatdo:lastProjectId', conversation.projectId);
    }
    
    // Set conversation immediately
    // Only change viewMode to 'chat' if we're not in a special view mode (like 'impact')
    const currentState = useChatStore.getState();
    set({ 
      currentConversation: conversation,
      viewMode: ['impact', 'memory'].includes(currentState.viewMode) ? currentState.viewMode : 'chat',
      // Clear ragFileIds immediately when switching conversations
      ragFileIds: []
    });
    
    // Load RAG files for this conversation (scoped per conversation)
    try {
      const ragResponse = await axios.get('http://localhost:8000/api/rag/files', {
        params: { chat_id: conversation.id }
      });
      const ragFiles: RagFile[] = ragResponse.data || [];
      // Sort by created_at to ensure consistent ordering (matches backend)
      const sortedFiles = ragFiles.sort((a, b) => 
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      // Store per conversation
      set((state) => ({
        ragFilesByConversationId: {
          ...state.ragFilesByConversationId,
          [conversation.id]: sortedFiles,
        },
        // Update ragFileIds for current conversation (only text_extracted files)
        ragFileIds: sortedFiles.filter((f) => f.text_extracted).map((f) => f.id),
      }));
      console.log(`[RAG] Loaded ${sortedFiles.length} files for conversation ${conversation.id}, ${sortedFiles.filter((f) => f.text_extracted).length} ready`);
    } catch (error) {
      // 404 is expected if no RAG files exist yet - initialize with empty array
      if ((error as any).response?.status !== 404) {
        console.error('Failed to load RAG files:', error);
      }
      // Initialize this conversation with empty RAG files
      set((state) => ({
        ragFilesByConversationId: {
          ...state.ragFilesByConversationId,
          [conversation.id]: [],
        },
        ragFileIds: [],
      }));
      console.log(`[RAG] Initialized empty RAG files for conversation ${conversation.id}`);
    }
    
    // Load messages from backend
    try {
      const response = await axios.get(`http://localhost:8000/api/chats/${conversation.id}/messages`);
      const backendMessages = response.data.messages || [];
      
      // Convert backend messages to frontend format
      // CRITICAL: Filter out RAG context preamble, system metadata, and oversized user messages
      console.log(`[DIAG] Loading ${backendMessages.length} messages from backend for conversation ${conversation.id}`);
      const messages: Message[] = [];
      
      for (let index = 0; index < backendMessages.length; index++) {
        const msg = backendMessages[index];
        
        // Filter out system-generated RAG metadata and oversized user messages
        const isRagPreamble = msg.content?.includes("You have access to the following reference documents") ||
                             msg.content?.includes("----\nSource:") ||
                             (msg.role === "user" && msg.content && msg.content.length > 2000);
        
        const isSystemMetadata = msg.type === "roleresume" ||
                                 msg.type === "rag_reference_preamble" ||
                                 msg.type === "reference_preamble" ||
                                 msg.role === "system";
        
        if (isRagPreamble || isSystemMetadata) {
          console.log(`[DIAG] Filtering out message ${index}: role=${msg.role}, type=${msg.type || 'none'}, length=${msg.content?.length || 0}, reason=${isRagPreamble ? 'RAG preamble' : 'system metadata'}`);
          continue; // Skip this message
        }
        
        // Debug: Log rag_response messages to verify they're being loaded
        if (msg.type === 'rag_response') {
          console.log('[RAG] Loading rag_response message:', { 
            type: msg.type, 
            hasData: !!msg.data, 
            dataKeys: msg.data ? Object.keys(msg.data) : [],
            content: msg.content?.substring(0, 50),
            dataContent: msg.data?.content?.substring(0, 50)
          });
        }
        
        // Convert legacy string[] sources to Source[] if needed
        let sources: Source[] | undefined = undefined;
        if (msg.sources) {
          if (Array.isArray(msg.sources) && msg.sources.length > 0) {
            // Check if already Source[] format
            if (typeof msg.sources[0] === 'object' && 'title' in msg.sources[0]) {
              sources = msg.sources as Source[];
            } else {
              // Convert string[] to Source[]
              // First pass: identify Memory vs Web sources
              const memorySources: string[] = [];
              const webSources: string[] = [];
              
              (msg.sources as string[]).forEach(source => {
                if (typeof source === 'string' && source.startsWith('Memory-')) {
                  memorySources.push(source);
                } else {
                  webSources.push(source);
                }
              });
              
              // Second pass: create Source objects with proper ranks
              sources = [
                // Web sources first (rank 0, 1, 2...)
                ...webSources.map((source, index) => ({
                  id: `web-${index}`,
                  title: source,
                  rank: index,
                  sourceType: 'web' as const,
                  citationPrefix: null, // Web uses no prefix: [1], [2], [3]
                })),
                // Memory sources second (rank 0, 1, 2... within Memory group)
                ...memorySources.map((source, index) => {
                  const sourceName = source.substring(7); // Remove "Memory-" prefix
                  return {
                    id: `memory-${index}`,
                    title: sourceName,
                    siteName: 'Memory',
                    description: 'Project memory source',
                    rank: index, // Rank within Memory group (0-based, will map to M1, M2, M3)
                    sourceType: 'memory' as const,
                    citationPrefix: 'M' as const, // Memory uses M prefix: [M1], [M2], [M3]
                  };
                })
              ];
            }
          }
        }
        
        // For web_search_results, convert results to sources if not already done
        if (msg.type === 'web_search_results' && msg.data?.results && (!sources || sources.length === 0)) {
          sources = msg.data.results.map((result: { title: string; url: string; snippet: string }, index: number) => {
            const extractDomain = (url: string): string => {
              try {
                const u = new URL(url);
                return u.hostname.replace(/^www\./, '');
              } catch {
                return url;
              }
            };
            return {
              id: `web-${index}`,
              url: result.url,
              title: result.title || result.url,
              siteName: extractDomain(result.url),
              description: result.snippet,
              rank: index,
              sourceType: 'web' as const,
              citationPrefix: null, // Web uses no prefix: [1], [2], [3]
            };
          });
        }
        
        // For rag_response, convert RAG files to sources if not already done
        if (msg.type === 'rag_response' && (!sources || sources.length === 0)) {
          const state = useChatStore.getState();
          const ragFiles = state.ragFilesByConversationId[conversation.id] || [];
          const readyFiles = ragFiles.filter((f: RagFile) => f.text_extracted);
          if (readyFiles.length > 0) {
            sources = readyFiles.map((file: RagFile, index: number) => ({
              id: file.id || `rag-${index}`,
              url: file.path ? `file://${file.path}` : undefined,
              title: file.filename || 'Document',
              siteName: 'My documents',
              description: 'Ready',
              rank: file.index || index, // Use file.index if available (1-based)
              sourceType: 'rag' as const,
              citationPrefix: 'R' as const, // RAG uses R prefix: [R1], [R2], [R3]
              fileName: file.filename,
            }));
          }
        }
        
        messages.push({
          id: msg.id || `${conversation.id}-${messages.length}`,  // Preserve backend message ID
          uuid: msg.uuid || msg.message_uuid,  // Preserve stable UUID from backend for deep-linking
          role: msg.role,
          content: msg.content || '',
          type: msg.type || undefined, // Preserve structured message types (article_card, web_search_results, rag_response)
          data: msg.data || undefined, // Preserve structured message data
          model: msg.model || undefined, // Preserve model attribution
          model_label: msg.model_label || undefined, // Preserve model_label from backend (most accurate)
          provider: msg.provider || undefined, // Preserve provider attribution
          sources: sources, // Use converted sources
          timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date(), // Use backend timestamp if available
          meta: msg.meta || undefined // Preserve meta including index_job, index_status, facts_actions, files_actions
        });
      }
      
      console.log(`[DIAG] Converted ${messages.length} messages for frontend (filtered ${backendMessages.length - messages.length} RAG/system messages)`);
      
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
        ),
        // Also update allConversations
        allConversations: state.allConversations.map(c =>
          c.id === conversation.id ? updatedConversation : c
        )
      }));
    } catch (error: any) {
      // Silently ignore 404s - chat might not exist or have no messages yet
      if (error.response?.status !== 404) {
        console.error('Failed to load messages:', error);
      }
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
      const now = new Date().toISOString();
      const updatedConversation = {
        ...state.currentConversation,
        messages: updatedMessages,
        updatedAt: now // Update timestamp when message is added
      };
      
      return {
        messages: updatedMessages,
        conversations: state.conversations.map(c =>
          c.id === updatedConversation.id ? updatedConversation : c
        ),
        allConversations: state.allConversations.map(c =>
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
        allConversations: state.allConversations.map(c =>
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
        allConversations: state.allConversations.map(c =>
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
        allConversations: state.allConversations.map(c =>
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
  
  setSummarizingArticle: (summarizing) => set({ isSummarizingArticle: summarizing }),  // Deprecated - kept for backward compatibility
  setConversationSummarizing: (conversationId, isSummarizing) => set((state) => {
    const newSet = new Set(state.summarizingConversations);
    if (isSummarizing && conversationId) {
      newSet.add(conversationId);
    } else if (conversationId) {
      newSet.delete(conversationId);
    }
    return { summarizingConversations: newSet };
  }),
  isConversationSummarizing: (conversationId) => {
    // @ts-ignore - Zustand circular reference pattern
    const state = useChatStore.getState();
    return conversationId ? state.summarizingConversations.has(conversationId) : false;
  },
  
  setRagTrayOpen: (open) => set({ isRagTrayOpen: open }),
  
  setRagFileIds: (ids) => set({ ragFileIds: ids }),
  
  setRagFilesForConversation: (conversationId, files) => {
    set((state) => ({
      ragFilesByConversationId: {
        ...state.ragFilesByConversationId,
        [conversationId]: files,
      },
      // Also update ragFileIds for backward compatibility
      ragFileIds: files.filter((f) => f.text_extracted).map((f) => f.id),
    }));
  },
  
  getRagFilesForConversation: (conversationId) => {
    if (!conversationId) return [];
    const state = useChatStore.getState();
    return state.ragFilesByConversationId[conversationId] || [];
  },
  
  // Sources management
  addSource: (source: Source) => set((state) => ({
    sources: [...state.sources, source]
  })),
  
  setSources: (sources: Source[]) => set({ sources }),
  
  loadSources: async (conversationId: string) => {
    try {
      // Load sources from backend
      const response = await axios.get(`http://localhost:8000/api/chats/${conversationId}/sources`);
      set({ sources: response.data.sources || [] });
    } catch (error: any) {
      // 404 is expected if no sources exist yet, don't log as error
      if (error.response?.status !== 404) {
        console.error('Failed to load sources:', error);
      }
      set({ sources: [] });
    }
  },
  
  setWebMode: (mode: WebMode) => set({ webMode: mode }),
  
  ensureGeneralProject: async () => {
    // @ts-ignore - Zustand circular reference pattern
    const state = useChatStore.getState();
    let generalProject = state.projects.find((p: Project) => p.name === 'General');
    
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
      // @ts-ignore - Zustand circular reference pattern
      const state = useChatStore.getState();
      const newConversation = state.conversations.find((c: Conversation) => c.id === conversationId);
      
      if (!newConversation) {
        throw new Error('Failed to find newly created conversation');
      }
      
      // Initialize new conversation with empty RAG files
      set((state) => ({
        ragFilesByConversationId: {
          ...state.ragFilesByConversationId,
          [conversationId]: [],
        },
        ragFileIds: [],
      }));
      
      // Reload all chats in the background to update allConversations with latest from all projects
      // This ensures the Recent section shows the correct chats
      setTimeout(() => {
        const { loadChats } = useChatStore.getState();
        loadChats(); // Load all chats (no project filter) to update allConversations
      }, 200);
      
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
  
  setSearchScope: (scope: string) => {
    set({ searchScope: scope });
  },

  searchChats: async (query: string, scope?: string) => {
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
    
    // Use provided scope or default from state
    const searchScope = scope || useChatStore.getState().searchScope;
    
    try {
      // Load chats based on scope
      const scopeParam = searchScope === 'all' ? 'all' : searchScope === 'active' ? 'active' : searchScope === 'archived' ? 'archived' : 'trash';
      const response = await axios.get(`http://localhost:8000/api/chats?scope=${scopeParam}`);
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
          } catch (err: any) {
            // If we can't load messages (404 or other error), just skip content search for this chat
            // Silently ignore 404s - chat might not exist or have no messages
            if (err.response?.status !== 404) {
              // Only log non-404 errors for debugging
              console.debug('Failed to load messages for search:', chat.id, err);
            }
          }
        }
        
        if (titleMatch || contentMatch) {
          const project = state.projects.find((p: Project) => p.id === chat.project_id);
          const defaultTarget = project?.default_target || 'general';
          
          const conversation: Conversation = {
            id: chat.id,
            title: chat.title,
            messages: [], // Will be loaded when opened
            projectId: chat.project_id,
            targetName: defaultTarget,
            createdAt: new Date(chat.created_at),
            updatedAt: chat.updated_at,  // Map updated_at from backend
            trashed: chat.trashed || false,
            trashed_at: chat.trashed_at,
            archived: chat.archived || false,
            archived_at: chat.archived_at,
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
  },
  
  openConnectProjectModal: (projectId: string, projectName: string) => {
    console.log('Opening Connect Project modal:', projectId, projectName);
    set({ 
      connectProjectModal: { 
        open: true, 
        projectId, 
        projectName 
      } 
    });
    console.log('Modal state set');
  },
  
  closeConnectProjectModal: () => {
    set({ 
      connectProjectModal: { 
        open: false 
      } 
    });
  }
}));

