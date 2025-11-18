import { create } from 'zustand';
import { v4 as uuidv4 } from 'uuid';

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
}

export interface Project {
  id: string;
  name: string;
  default_target: string;
}

interface ChatStore {
  // State
  projects: Project[];
  currentProject: Project | null;
  conversations: Conversation[];
  currentConversation: Conversation | null;
  messages: Message[];
  isLoading: boolean;
  isStreaming: boolean;
  streamingContent: string;
  
  // Actions
  setProjects: (projects: Project[]) => void;
  setCurrentProject: (project: Project | null) => void;
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  setCurrentConversation: (conversation: Conversation | null) => void;
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
  currentConversation: null,
  messages: [],
  isLoading: false,
  isStreaming: false,
  streamingContent: '',
  
  // Actions
  setProjects: (projects) => set({ projects }),
  
  setCurrentProject: (project) => set({ currentProject: project }),
  
  setConversations: (conversations) => set({ conversations }),
  
  addConversation: (conversation) => set((state) => ({
    conversations: [conversation, ...state.conversations]
  })),
  
  setCurrentConversation: (conversation) => set({ 
    currentConversation: conversation,
    messages: conversation?.messages || []
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

