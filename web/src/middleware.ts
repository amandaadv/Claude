import { withAuth } from "next-auth/middleware";

export default withAuth({
  pages: { signIn: "/login" },
});

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/catalogos/:path*",
    "/fila/:path*",
    "/pedidos/:path*",
    "/precos/:path*",
    "/representantes/:path*",
    "/configuracoes/:path*",
  ],
};
