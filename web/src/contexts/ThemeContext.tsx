import React, { createContext, useContext, useEffect, useState } from 'react';

type Theme = 'light' | 'dark';
type AccentColor = 'default' | 'orange' | 'yellow' | 'green' | 'blue' | 'pink' | 'purple';

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
  accentColor: AccentColor;
  setAccentColor: (color: AccentColor) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<Theme>(() => {
    // Check localStorage first, then system preference, default to dark
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('theme') as Theme | null;
      if (saved) return saved;
      
      // Check system preference
      if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
      }
    }
    return 'dark'; // Default to dark to match current design
  });

  const [accentColor, setAccentColorState] = useState<AccentColor>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('accentColor') as AccentColor | null;
      return saved || 'default';
    }
    return 'default';
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    // Helper function to convert hex to RGB
    const hexToRgb = (hex: string): [number, number, number] => {
      const color = hex.replace('#', '');
      const r = parseInt(color.substring(0, 2), 16);
      const g = parseInt(color.substring(2, 4), 16);
      const b = parseInt(color.substring(4, 6), 16);
      return [r, g, b];
    };

    // Helper function to convert RGB to HSL
    const rgbToHsl = (r: number, g: number, b: number): [number, number, number] => {
      r /= 255;
      g /= 255;
      b /= 255;
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      let h = 0, s = 0;
      const l = (max + min) / 2;

      if (max !== min) {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        switch (max) {
          case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
          case g: h = ((b - r) / d + 2) / 6; break;
          case b: h = ((r - g) / d + 4) / 6; break;
        }
      }
      return [h * 360, s * 100, l * 100];
    };

    // Helper function to convert HSL to RGB
    const hslToRgb = (h: number, s: number, l: number): [number, number, number] => {
      h /= 360;
      s /= 100;
      l /= 100;
      let r, g, b;

      if (s === 0) {
        r = g = b = l;
      } else {
        const hue2rgb = (p: number, q: number, t: number) => {
          if (t < 0) t += 1;
          if (t > 1) t -= 1;
          if (t < 1/6) return p + (q - p) * 6 * t;
          if (t < 1/2) return q;
          if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
          return p;
        };
        const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
        const p = 2 * l - q;
        r = hue2rgb(p, q, h + 1/3);
        g = hue2rgb(p, q, h);
        b = hue2rgb(p, q, h - 1/3);
      }
      return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
    };

    // Helper function to convert RGB to hex
    const rgbToHex = (r: number, g: number, b: number): string => {
      return '#' + [r, g, b].map(x => {
        const hex = x.toString(16);
        return hex.length === 1 ? '0' + hex : hex;
      }).join('');
    };

    // Soften color: +12% lightness, -8% saturation (applied twice for extra softness)
    const softenColor = (hex: string): string => {
      const [r, g, b] = hexToRgb(hex);
      let [h, s, l] = rgbToHsl(r, g, b);
      
      // Apply softening twice: +12% lightness, -8% saturation each time
      for (let i = 0; i < 2; i++) {
        // Increase lightness by 12%
        l = Math.min(100, l + 12);
        
        // Decrease saturation by 8%
        s = Math.max(0, s - 8);
      }
      
      const [newR, newG, newB] = hslToRgb(h, s, l);
      return rgbToHex(newR, newG, newB);
    };

    // Apply accent color as CSS variable - using ChatGPT's exact macOS accent colors, softened
    const root = document.documentElement;
    const accentColors: Record<AccentColor, string> = {
      default: '#8C8C8C', // Graphite gray (ChatGPT's default)
      orange: '#F7821B',
      yellow: '#FFC600',
      green: '#62BA46',
      blue: '#007AFF',
      pink: '#F74F9E',
      purple: '#A550A7',
    };
    
    // Soften all colors: +12% lightness, -8% saturation
    const softenedColors: Record<AccentColor, string> = {
      default: softenColor(accentColors.default),
      orange: softenColor(accentColors.orange),
      yellow: softenColor(accentColors.yellow),
      green: softenColor(accentColors.green),
      blue: softenColor(accentColors.blue),
      pink: softenColor(accentColors.pink),
      purple: softenColor(accentColors.purple),
    };
    
    const accentTextColors: Record<AccentColor, string> = {
      default: '#000000', // Black text for graphite
      orange: '#000000', // Black text for orange
      yellow: '#000000', // Black text for yellow
      green: '#000000', // Black text for green
      blue: '#FFFFFF', // White text for blue
      pink: '#FFFFFF', // White text for pink
      purple: '#FFFFFF', // White text for purple
    };
    
    root.style.setProperty('--user-bubble-bg', softenedColors[accentColor]);
    root.style.setProperty('--user-bubble-text', accentTextColors[accentColor]);
    localStorage.setItem('accentColor', accentColor);
  }, [accentColor]);

  const toggleTheme = () => {
    setThemeState(prev => prev === 'light' ? 'dark' : 'light');
  };

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
  };

  const setAccentColor = (color: AccentColor) => {
    setAccentColorState(color);
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme, accentColor, setAccentColor }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

