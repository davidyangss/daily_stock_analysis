import type React from 'react';
import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Drawer } from '../common/Drawer';
import { SidebarNav } from './SidebarNav';
import { ShellHeader } from './ShellHeader';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

type ShellProps = {
  children?: React.ReactNode;
};

export const Shell: React.FC<ShellProps> = ({ children }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const { t } = useUiLanguage();

  return (
    <div className="min-h-[100dvh] bg-background text-foreground">
      <ShellHeader onOpenNav={() => setMenuOpen(true)} />

      <div className="mx-auto w-full max-w-[1680px] sm:px-4 lg:px-5">
        <main className="min-h-0 min-w-0 touch-pan-y">
          {children ?? <Outlet />}
        </main>
      </div>

      <Drawer
        isOpen={menuOpen}
        onClose={() => setMenuOpen(false)}
        title={t('layout.navMenu')}
        width="max-w-xs"
        zIndex={90}
        side="left"
      >
        <SidebarNav onNavigate={() => setMenuOpen(false)} />
      </Drawer>
    </div>
  );
};
