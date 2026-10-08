export async function submitPayment(amount: string) {
  const response = await fetch("http://payments.demo:9000/payments?amount=" + amount, { method: "POST" });
  if (!response.ok) throw new Error("Payment was rejected");
  return response.json();
}
