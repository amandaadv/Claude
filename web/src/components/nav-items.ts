import {
  LayoutDashboard,
  LibraryBig,
  ListOrdered,
  ShoppingBag,
  Tags,
  Users,
  Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Início", icon: LayoutDashboard },
  { href: "/catalogos", label: "Catálogos", icon: LibraryBig },
  { href: "/fila", label: "Fila de Produção", icon: ListOrdered },
  { href: "/pedidos", label: "Pedidos do Site", icon: ShoppingBag },
  { href: "/precos", label: "Tabela de Preços", icon: Tags },
  { href: "/representantes", label: "Representantes", icon: Users },
  { href: "/configuracoes", label: "Configurações", icon: Settings },
];
