-- Demo schema for the Agent + DB (backendless) stack.
-- Everything created here is auto-tracked by Hasura when the FastAPI app boots
-- (app/bootstrap.py reads information_schema and tracks tables + FK relationships).

create table public.users (
  id         serial primary key,
  name       text not null,
  email      text not null unique,
  created_at timestamptz not null default now()
);

create table public.products (
  id       serial primary key,
  name     text not null,
  category text not null default 'general',
  price    numeric(10,2) not null check (price >= 0),
  stock    integer not null default 0
);

create table public.orders (
  id         serial primary key,
  user_id    integer not null references public.users(id) on delete cascade,
  status     text not null default 'pending',
  total      numeric(10,2) not null default 0,
  created_at timestamptz not null default now()
);

create table public.order_items (
  id         serial primary key,
  order_id   integer not null references public.orders(id) on delete cascade,
  product_id integer not null references public.products(id),
  quantity   integer not null default 1 check (quantity > 0),
  unit_price numeric(10,2) not null
);

insert into public.users (name, email) values
  ('Ada Lovelace',  'ada@example.com'),
  ('Alan Turing',   'alan@example.com'),
  ('Grace Hopper',  'grace@example.com');

insert into public.products (name, category, price, stock) values
  ('Mechanical Keyboard',    'hardware',    89.90, 25),
  ('Noise-Cancelling Headset','hardware',  149.00, 12),
  ('USB-C Hub',              'accessories', 39.50, 60),
  ('Monitor Light Bar',      'accessories', 54.00,  3);

insert into public.orders (user_id, status, total) values
  (1, 'shipped',   149.00),
  (2, 'pending',   168.90),
  (3, 'delivered', 197.90);

insert into public.order_items (order_id, product_id, quantity, unit_price) values
  (1, 2, 1, 149.00),
  (2, 3, 2,  39.50),
  (2, 1, 1,  89.90),
  (3, 1, 1,  89.90),
  (3, 4, 2,  54.00);

-- ── Extended demo data (same shape as the live insert script) ──────────────
-- Edsger Dijkstra has no orders; HDMI Cable 2m is never ordered; order 13's
-- total (250.00) intentionally mismatches its items (114.80) so the agent has
-- real cases for "users with no orders", "products never sold" and data-quality checks.

insert into public.users (name, email) values
  ('Nikola Tesla',      'nikola@example.com'),
  ('Marie Curie',       'marie@example.com'),
  ('Katherine Johnson', 'katherine@example.com'),
  ('Rosalind Franklin', 'rosalind@example.com'),
  ('Edsger Dijkstra',   'edsger@example.com');

insert into public.products (name, category, price, stock) values
  ('Wireless Mouse',   'accessories', 24.90, 80),
  ('Laptop Stand',     'hardware',    42.00, 18),
  ('Desk Mat',         'accessories', 29.00, 40),
  ('HDMI Cable 2m',    'accessories',  9.90, 50);

insert into public.orders (user_id, status, total, created_at) values
  (4, 'delivered',  49.80, '2026-09-28'),
  (5, 'delivered',  66.90, '2026-10-05'),
  (6, 'delivered',  68.50, '2026-10-12'),
  (7, 'shipped',    89.90, '2026-10-20'),
  (2, 'pending',   228.00, '2026-11-02'),
  (5, 'cancelled',  54.00, '2026-11-05'),
  (7, 'pending',    82.90, '2026-11-10'),
  (4, 'shipped',    71.00, '2026-11-13'),
  (6, 'pending',   118.50, '2026-11-16'),
  (1, 'shipped',   250.00, '2026-11-08');

insert into public.order_items (order_id, product_id, quantity, unit_price) values
  (4, 5, 2,  24.90),
  (5, 6, 1,  42.00), (5, 5, 1,  24.90),
  (6, 7, 1,  29.00), (6, 3, 1,  39.50),
  (7, 1, 1,  89.90),
  (8, 2, 1, 149.00), (8, 3, 2,  39.50),
  (9, 4, 1,  54.00),
  (10, 7, 2, 29.00), (10, 5, 1, 24.90),
  (11, 6, 1, 42.00), (11, 7, 1, 29.00),
  (12, 3, 3, 39.50),
  (13, 1, 1, 89.90), (13, 5, 1, 24.90);
