namespace My.Component.Tests;

public class CalculatorTests
{
    [Fact]
    [Trait("Category", "Integration")]
    public void Adds() => Assert.Equal(4, new Calculator().Add(2, 2));

    [Fact]
    [Trait("Category", "Integration")]
    public void Divides() => Assert.Equal(3, new Calculator().Divide(9, 3));

    [Fact]
    [Trait("Category", "Integration")]
    public void RejectsDivisionByZero() =>
        Assert.Throws<DivideByZeroException>(() => new Calculator().Divide(1, 0));

    [Fact]
    [Trait("Category", "Unit")]
    public void NotSelectedByTheIntegrationFilter() =>
        Assert.Fail("этот тест не должен запускаться под фильтром Category=Integration");
}
