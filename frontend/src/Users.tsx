import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, json, type components } from "./api/client";
import { ErrorMessage } from "./ErrorMessage";

type Schemas = components["schemas"];
type Role = Schemas["UserRole"];
const labels: Record<Role, string> = {
  user: "Пользователь",
  kb_expert: "Эксперт нормативной базы",
  org_admin: "Администратор организации",
  service_admin: "Администратор сервиса",
};
const pageSize = 20;

export function Users({ current }: { current: Schemas["MeOut"] }) {
  const serviceAdmin = current.role === "service_admin";
  const roles = serviceAdmin ? Object.keys(labels) as Role[] : ["user", "org_admin"] as const;
  const [page, setPage] = useState(1);
  const cache = useQueryClient();
  const users = useQuery({
    queryKey: ["users", page],
    queryFn: () => api<Schemas["Page_UserOut_"]>(`/users?page=${page}&page_size=${pageSize}`),
  });
  const organizations = useQuery({
    queryKey: ["organizations"],
    queryFn: () => api<Schemas["OrganizationOut"][]>("/organizations"),
    enabled: serviceAdmin,
  });
  const create = useMutation({
    mutationFn: (body: Schemas["UserCreate"]) => api<Schemas["UserOut"]>("/users", json(body)),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["users"] }),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["UserUpdate"] }) =>
      api<Schemas["UserOut"]>(`/users/${id}`, { ...json(body), method: "PATCH" }),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["users"] });
      await cache.invalidateQueries({ queryKey: ["session"] });
    },
  });
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const organization = values.get("organization_id");
    try {
      await create.mutateAsync({
        email: String(values.get("email")).trim(),
        full_name: String(values.get("full_name")).trim(),
        password: String(values.get("password")),
        role: String(values.get("role")) as Role,
        ...(organization ? { organization_id: String(organization) } : {}),
      });
      form.reset();
    } catch {
      // Ошибка отображается из состояния запроса.
    }
  }
  return <section className="panel">
    <h1>Пользователи</h1>
    <ErrorMessage error={users.error ?? organizations.error ?? update.error} />
    {users.isPending && <p role="status">Загрузка пользователей…</p>}
    {users.data && <>
      <div className="table-scroll">
        <table className="history-table">
          <thead><tr><th>Пользователь</th><th>Роль</th><th>Статус</th><th>Действия</th></tr></thead>
          <tbody>{users.data.items.map(user => {
            const editable = (roles as readonly Role[]).includes(user.role) && user.id !== current.id;
            return <tr key={user.id}>
              <td>{user.full_name}<br /><span className="muted">{user.email}</span>
                {serviceAdmin && <><br /><span className="muted">{organizations.data?.find(org => org.id === user.organization_id)?.name ?? user.organization_id}</span></>}
              </td>
              <td>{editable ? <select aria-label={`Роль ${user.email}`} value={user.role} disabled={update.isPending}
                onChange={event => update.mutate({ id: user.id, body: { role: event.target.value as Role } })}>
                {roles.map(role => <option key={role} value={role}>{labels[role]}</option>)}
              </select> : labels[user.role]}</td>
              <td>{user.is_active ? "Активен" : "Заблокирован"}</td>
              <td>{editable && <button className="secondary" disabled={update.isPending} onClick={() => {
                if (window.confirm(`${user.is_active ? "Заблокировать" : "Разблокировать"} пользователя ${user.email}?`)) {
                  update.mutate({ id: user.id, body: { is_active: !user.is_active } });
                }
              }}>{user.is_active ? "Заблокировать" : "Разблокировать"}</button>}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {!users.data.items.length && <p>Пользователей на этой странице нет.</p>}
      {(page > 1 || users.data.total > pageSize) && <div className="actions">
        <button className="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Назад</button>
        <span>Страница {page}</span>
        <button className="secondary" disabled={page * pageSize >= users.data.total} onClick={() => setPage(page + 1)}>Далее</button>
      </div>}
    </>}
    <form className="admin-form" onSubmit={submit}>
      <h2>Новый пользователь</h2>
      <label>Имя<input name="full_name" required pattern=".*\S.*" /></label>
      <label>Электронная почта<input name="email" type="email" maxLength={320} required /></label>
      <label>Начальный пароль<input name="password" type="password" autoComplete="new-password" minLength={8} required /></label>
      <label>Роль<select name="role" defaultValue="user">{roles.map(role => <option key={role} value={role}>{labels[role]}</option>)}</select></label>
      {serviceAdmin && <label>Организация<select name="organization_id" defaultValue="">
        <option value="">Моя организация</option>
        {organizations.data?.filter(org => org.is_active && org.id !== current.organization_id).map(org =>
          <option key={org.id} value={org.id}>{org.name}</option>)}
      </select></label>}
      <button disabled={create.isPending}>Создать пользователя</button>
      {create.isSuccess && <p role="status">Пользователь создан.</p>}
      <ErrorMessage error={create.error} />
    </form>
  </section>;
}
