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

export type ViewMode = 'projectList' | 'chat' | 'trashList';

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
  
  // Actions
  setProjects: (projects: Project[]) => void;
  setCurrentProject: (project: Project | null) => void;
  setViewMode: (mode: ViewMode) => void;
  loadProjects: () => Promise<void>;
  createProject: (name: string) => Promise<void>;
  renameProject: (id: string, name: string) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  reorderProjects: (orderedIds: string[]) => Promise<void>;
  loadChats: (projectId?: string) => Promise<void>;
  loadTrashedChats: () => Promise<void>;
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  setCurrentConversation: (conversation: Conversation | null) => void;
  renameChat: (id: string, title: string) => Promise<void>;
  deleteChat: (id: string) => Promise<void>;
  restoreChat: (id: string) => Promise<void>;
  purgeChat: (id: string) => Promise<void>;
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void;
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
  
  // Actions
  setProjects: (projects) => set({ projects }),
  
  setCurrentProject: (project) => {
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
        // If no current project is set and we have projects, select the first one
        const newCurrentProject = !state.currentProject && projects.length > 0
          ? projects[0]
          : state.currentProject;
        return { 
          projects, 
          currentProject: newCurrentProject,
          viewMode: newCurrentProject ? 'projectList' : state.viewMode
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
      const url = projectId
        ? `http://localhost:8000/api/chats?project_id=${projectId}&include_trashed=true`
        : `http://localhost:8000/api/chats?include_trashed=true`;
      const response = await axios.get(url);
      const allChats = response.data;
      
      // Get the project to find default_target
      const state = useChatStore.getState();
      const project = projectId 
        ? state.projects.find(p => p.id === projectId) || state.currentProject
        : state.currentProject;
      const defaultTarget = project?.default_target || 'general';
      
      // Convert to Conversation format and split active/trashed
      const activeChats: Conversation[] = [];
      const trashedChats: Conversation[] = [];
      
      for (const chat of allChats) {
        const conversation: Conversation = {
          id: chat.id,
          title: chat.title,
          messages: [], // Messages loaded separately if needed
          projectId: chat.project_id,
          targetName: defaultTarget,
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
    } catch (error) {
      console.error('Failed to purge chat:', error);
      throw error;
    }
  },
  
  setCurrentConversation: (conversation) => set({ 
    currentConversation: conversation,
    messages: conversation?.messages || [],
    viewMode: conversation ? 'chat' : 'projectList'
  }),
  
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
        currentConversation: updatedConversation
      };
    }
    
    return { messages: updatedMessages };
  }),
  
  updateStreamingContent: (content) => set({ streamingContent: content }),
  
  setLoading: (loading) => set({ isLoading: loading }),
  
  setStreaming: (streaming) => set({ isStreaming: streaming }),
  
  clearStreaming: () => set({ isStreaming: false, streamingContent: '' })
}));

