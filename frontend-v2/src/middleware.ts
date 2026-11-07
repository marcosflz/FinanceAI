import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIES = ["__Host-ft_session", "ft_session"];

function hasSessionCookie(request: NextRequest): boolean {
  return SESSION_COOKIES.some((name) => request.cookies.has(name));
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const isLogin = pathname === "/login";
  const authenticated = hasSessionCookie(request);

  if (!authenticated && !isLogin) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }

  const response = NextResponse.next();
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  return response;
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|icon.svg|robots.txt|sitemap.xml|.*\\..*).*)",
  ],
};
