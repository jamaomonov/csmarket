interface StarsTextProps {
  rating: number;
}

/** «★★☆☆☆», read as «2 из 5»; bad ones in the danger colour. */
export function StarsText({ rating }: StarsTextProps) {
  return (
    <span
      role="img"
      aria-label={`${String(rating)} из 5`}
      className={rating >= 4 ? "text-warning" : "text-danger"}
    >
      {"★".repeat(rating)}
      {"☆".repeat(5 - rating)}
    </span>
  );
}
