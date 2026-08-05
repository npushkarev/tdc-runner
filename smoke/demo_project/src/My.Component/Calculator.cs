namespace My.Component;

/// Продуктовый код. Нужен, чтобы покрытие считалось по нему, а не по тестам.
public sealed class Calculator
{
    public int Add(int a, int b) => a + b;

    public int Divide(int a, int b)
    {
        if (b == 0) throw new DivideByZeroException();
        return a / b;
    }

    /// Намеренно не вызывается: покрытие должно быть меньше ста процентов.
    public string Describe() => "calculator";
}
