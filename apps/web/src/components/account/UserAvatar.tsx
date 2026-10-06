import { cn } from "@csmarket/ui";
import { User } from "lucide-react";

interface UserAvatarProps {
  user: { avatar_url: string | null; display_name: string | null };
  /** Square size in px (default 28). */
  size?: number;
  className?: string;
}

/** The Steam avatar, or the name's first letter on the accent tint when Steam gave none. */
export function UserAvatar({ user, size = 28, className }: UserAvatarProps) {
  const box = cn("shrink-0 rounded-lg", className);
  if (user.avatar_url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- Steam CDN avatars; next/image would need remotePatterns per CDN host
      <img src={user.avatar_url} alt="" width={size} height={size} className={box} />
    );
  }
  const first = user.display_name?.trim().charAt(0).toUpperCase();
  const initial = first === "" ? undefined : first;
  return (
    <span
      aria-hidden
      style={{ width: size, height: size, fontSize: Math.round(size * 0.45) }}
      className={cn(box, "bg-accent-subtle text-accent grid place-items-center font-bold")}
    >
      {initial ?? <User style={{ width: size * 0.5, height: size * 0.5 }} />}
    </span>
  );
}
